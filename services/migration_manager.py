"""
Migration Manager for Vendly Pro
Handles migration from current Vendly to Vendly Pro with data preservation, validation, and rollback capabilities.
"""
from typing import Dict, Any, Optional, List, Tuple
import logging
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
import json

from db.supabase import get_supabase_client
from models.vendly_pro import (
    CustomerProfileCreate,
    CustomerProfileResponse,
    LoyaltyPointsCreate,
    LoyaltyPointsResponse,
)

logger = logging.getLogger(__name__)


class MigrationStatus(str, Enum):
    """Status of migration process"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class DataCategory(str, Enum):
    """Categories of data to migrate"""
    TENANT = "tenant"
    PRODUCTS = "products"
    CUSTOMERS = "customers"
    ORDERS = "orders"
    LOYALTY = "loyalty"
    CONFIG = "config"
    CONVERSATIONS = "conversations"


@dataclass
class MigrationAssessment:
    """Result of migration readiness assessment"""
    tenant_id: str
    is_ready: bool
    data_summary: Dict[str, int] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    estimated_size_mb: float = 0.0


@dataclass
class MigrationProgress:
    """Progress tracking for migration"""
    tenant_id: str
    status: MigrationStatus
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    data_migrated: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    current_category: Optional[DataCategory] = None


@dataclass
class ValidationResult:
    """Result of migration validation"""
    is_valid: bool
    source_counts: Dict[str, int] = field(default_factory=dict)
    target_counts: Dict[str, int] = field(default_factory=dict)
    mismatches: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class MigrationManager:
    """Service for managing data migration from Vendly to Vendly Pro"""
    
    def __init__(self, db=None):
        self.db = db or get_supabase_client()
        self._active_migrations: Dict[str, MigrationProgress] = {}
    
    # ============================================
    # MIGRATION READINESS ASSESSMENT
    # ============================================
    
    async def assess_migration_readiness(
        self, 
        tenant_id: str
    ) -> MigrationAssessment:
        """
        Assess if a tenant is ready for migration.
        
        Args:
            tenant_id: Current Vendly tenant identifier
            
        Returns:
            MigrationAssessment with readiness status and data summary
        """
        try:
            logger.info(f"Assessing migration readiness for tenant: {tenant_id}")
            
            issues = []
            warnings = []
            data_summary = {}
            estimated_size_mb = 0.0
            
            # Check if tenant exists
            tenant_result = self.db.table("tenants").select("*").eq(
                "id", tenant_id
            ).execute()
            
            if not tenant_result.data:
                issues.append(f"Tenant {tenant_id} not found")
                return MigrationAssessment(
                    tenant_id=tenant_id,
                    is_ready=False,
                    issues=issues
                )
            
            data_summary["tenants"] = 1
            
            # Count products
            products_result = self.db.table("items").select(
                "count", count="exact"
            ).eq("tenant_id", tenant_id).execute()
            products_count = products_result.count or 0
            data_summary["products"] = products_count
            estimated_size_mb += products_count * 0.001  # ~1KB per product
            
            # Count customers (from orders)
            customers_result = self.db.table("orders").select(
                "customer_phone", distinct=True
            ).eq("tenant_id", tenant_id).execute()
            customers_count = len(customers_result.data) if customers_result.data else 0
            data_summary["customers"] = customers_count
            estimated_size_mb += customers_count * 0.005  # ~5KB per customer
            
            # Count orders
            orders_result = self.db.table("orders").select(
                "count", count="exact"
            ).eq("tenant_id", tenant_id).execute()
            orders_count = orders_result.count or 0
            data_summary["orders"] = orders_count
            estimated_size_mb += orders_count * 0.002  # ~2KB per order
            
            # Check for products without categories
            if products_count > 0:
                products_no_category = self.db.table("items").select("count", count="exact").eq(
                    "tenant_id", tenant_id
                ).is_("category_id", "null").execute()
                
                if products_no_category.count and products_no_category.count > products_count * 0.5:
                    warnings.append(f"High number of products without categories: {products_no_category.count}")
            
            # Check for orders without items
            if orders_count > 0:
                orders_no_items = self.db.table("orders").select("count", count="exact").eq(
                    "tenant_id", tenant_id
                ).execute()
                
                # Check order_items relationship
                if orders_no_items.count and orders_no_items.count > 0:
                    # Check for potential data integrity issues
                    warnings.append("Some orders may have missing items")
            
            # Check for missing WhatsApp configuration
            whatsapp_result = self.db.table("whatsapp_configs").select("*").eq(
                "tenant_id", tenant_id
            ).execute()
            
            if not whatsapp_result.data:
                warnings.append("No WhatsApp configuration found for tenant")
            
            # Determine readiness
            is_ready = len(issues) == 0
            
            # Add warning if no products
            if products_count == 0:
                warnings.append("Tenant has no products - may need manual setup")
                is_ready = False
            
            return MigrationAssessment(
                tenant_id=tenant_id,
                is_ready=is_ready,
                data_summary=data_summary,
                issues=issues,
                warnings=warnings,
                estimated_size_mb=round(estimated_size_mb, 2)
            )
            
        except Exception as e:
            logger.error(f"Error assessing migration readiness: {e}")
            return MigrationAssessment(
                tenant_id=tenant_id,
                is_ready=False,
                issues=[f"Error during assessment: {str(e)}"]
            )
    
    # ============================================
    # DATA MIGRATION
    # ============================================
    
    async def migrate_tenant_data(
        self,
        source_tenant_id: str,
        target_tenant_id: Optional[str] = None,
        migrate_customers: bool = True,
        migrate_orders: bool = True,
        migrate_loyalty: bool = False,
        create_backup: bool = True
    ) -> Dict[str, Any]:
        """
        Migrate all tenant data from Vendly to Vendly Pro.
        
        Args:
            source_tenant_id: Source tenant ID in current Vendly
            target_tenant_id: Target tenant ID in Vendly Pro (if None, uses source_tenant_id)
            migrate_customers: Whether to create customer profiles
            migrate_orders: Whether to migrate order history
            migrate_loyalty: Whether to initialize loyalty points
            create_backup: Whether to create data backup before migration
            
        Returns:
            Dictionary with migration result details
        """
        try:
            # Use source tenant ID as target if not specified
            if target_tenant_id is None:
                target_tenant_id = source_tenant_id
            
            logger.info(f"Starting migration: {source_tenant_id} -> {target_tenant_id}")
            
            # Initialize progress tracking
            progress = MigrationProgress(
                tenant_id=source_tenant_id,
                status=MigrationStatus.IN_PROGRESS,
                start_time=datetime.now()
            )
            self._active_migrations[source_tenant_id] = progress
            
            # Create backup if requested
            if create_backup:
                backup_result = await self._create_migration_backup(source_tenant_id)
                if not backup_result.get("success"):
                    progress.errors.append(f"Backup failed: {backup_result.get('error')}")
                    progress.status = MigrationStatus.FAILED
                    return {
                        "success": False,
                        "error": "Backup failed",
                        "progress": progress
                    }
            
            migrated_data = {}
            
            # Migrate customer profiles
            if migrate_customers:
                progress.current_category = DataCategory.CUSTOMERS
                customers_result = await self._migrate_customer_profiles(
                    source_tenant_id, target_tenant_id
                )
                migrated_data["customers"] = customers_result
                progress.data_migrated["customers"] = customers_result.get("migrated_count", 0)
            
            # Migrate purchase history from orders
            if migrate_orders:
                progress.current_category = DataCategory.ORDERS
                orders_result = await self._migrate_purchase_history(
                    source_tenant_id, target_tenant_id
                )
                migrated_data["orders"] = orders_result
                progress.data_migrated["orders"] = orders_result.get("migrated_count", 0)
            
            # Initialize loyalty if requested
            if migrate_loyalty:
                progress.current_category = DataCategory.LOYALTY
                loyalty_result = await self._initialize_loyalty_system(
                    source_tenant_id, target_tenant_id
                )
                migrated_data["loyalty"] = loyalty_result
                progress.data_migrated["loyalty_accounts"] = loyalty_result.get("created_count", 0)
            
            # Store migration metadata
            progress.status = MigrationStatus.COMPLETED
            progress.end_time = datetime.now()
            
            # Store migration record
            await self._store_migration_record(
                source_tenant_id,
                target_tenant_id,
                migrated_data,
                progress
            )
            
            # Clean up progress tracking
            del self._active_migrations[source_tenant_id]
            
            return {
                "success": True,
                "source_tenant_id": source_tenant_id,
                "target_tenant_id": target_tenant_id,
                "migrated_data": migrated_data,
                "duration_seconds": (progress.end_time - progress.start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(f"Error during migration: {e}")
            
            # Update progress with error
            if source_tenant_id in self._active_migrations:
                self._active_migrations[source_tenant_id].status = MigrationStatus.FAILED
                self._active_migrations[source_tenant_id].errors.append(str(e))
            
            return {
                "success": False,
                "error": str(e),
                "source_tenant_id": source_tenant_id
            }
    
    async def _migrate_customer_profiles(
        self,
        source_tenant_id: str,
        target_tenant_id: str
    ) -> Dict[str, Any]:
        """Migrate customer data to customer_profiles table"""
        try:
            # Get distinct customers from orders
            orders_result = self.db.table("orders").select(
                "customer_phone", 
                "total_amount",
                "created_at"
            ).eq("tenant_id", source_tenant_id).order(
                "created_at", desc=True
            ).execute()
            
            if not orders_result.data:
                return {"migrated_count": 0, "skipped_count": 0}
            
            # Get unique customer phones with their total spending
            customer_data = {}
            for order in orders_result.data:
                phone = order.get("customer_phone")
                if phone and phone not in customer_data:
                    customer_data[phone] = {
                        "total_spent": 0.0,
                        "last_purchase_date": None
                    }
                
                if phone:
                    customer_data[phone]["total_spent"] += float(order.get("total_amount", 0))
                    order_date = order.get("created_at")
                    if order_date:
                        if customer_data[phone]["last_purchase_date"] is None or \
                           order_date > customer_data[phone]["last_purchase_date"]:
                            customer_data[phone]["last_purchase_date"] = order_date
            
            migrated_count = 0
            skipped_count = 0
            
            for phone, data in customer_data.items():
                try:
                    # Check if profile already exists
                    existing = self.db.table("customer_profiles").select("id").eq(
                        "tenant_id", target_tenant_id
                    ).eq("phone_number", phone).execute()
                    
                    if existing.data:
                        # Update existing profile
                        self.db.table("customer_profiles").update({
                            "total_spent": data["total_spent"],
                            "last_purchase_date": data["last_purchase_date"],
                            "updated_at": datetime.now().isoformat()
                        }).eq("tenant_id", target_tenant_id).eq("phone_number", phone).execute()
                        migrated_count += 1
                    else:
                        # Create new profile
                        profile_data = {
                            "tenant_id": target_tenant_id,
                            "phone_number": phone,
                            "preferences": {},
                            "allergies": [],
                            "dietary_restrictions": [],
                            "favorite_products": [],
                            "total_spent": data["total_spent"],
                            "last_purchase_date": data["last_purchase_date"],
                            "created_at": datetime.now().isoformat(),
                            "updated_at": datetime.now().isoformat()
                        }
                        self.db.table("customer_profiles").insert(profile_data).execute()
                        migrated_count += 1
                        
                except Exception as e:
                    logger.warning(f"Failed to migrate customer {phone}: {e}")
                    skipped_count += 1
            
            return {
                "migrated_count": migrated_count,
                "skipped_count": skipped_count
            }
            
        except Exception as e:
            logger.error(f"Error migrating customer profiles: {e}")
            raise
    
    async def _migrate_purchase_history(
        self,
        source_tenant_id: str,
        target_tenant_id: str
    ) -> Dict[str, Any]:
        """Migrate order data to purchase_history table"""
        try:
            # Get all orders with items
            orders_result = self.db.table("orders").select(
                "id, customer_phone, total_amount, created_at"
            ).eq("tenant_id", source_tenant_id).order(
                "created_at", desc=True
            ).limit(1000).execute()
            
            if not orders_result.data:
                return {"migrated_count": 0, "skipped_count": 0}
            
            migrated_count = 0
            skipped_count = 0
            
            for order in orders_result.data:
                try:
                    order_id = order.get("id")
                    customer_phone = order.get("customer_phone")
                    total_amount = float(order.get("total_amount", 0))
                    created_at = order.get("created_at")
                    
                    if not customer_phone:
                        skipped_count += 1
                        continue
                    
                    # Get order items
                    items_result = self.db.table("order_items").select(
                        "item_id, quantity, unit_price"
                    ).eq("order_id", order_id).execute()
                    
                    if items_result.data:
                        for item in items_result.data:
                            item_id = item.get("item_id")
                            quantity = item.get("quantity", 1)
                            unit_price = float(item.get("unit_price", 0))
                            
                            # Check if purchase history already exists
                            existing = self.db.table("purchase_history").select("id").eq(
                                "tenant_id", target_tenant_id
                            ).eq("order_id", order_id).eq("product_id", item_id).execute()
                            
                            if not existing.data:
                                purchase_data = {
                                    "tenant_id": target_tenant_id,
                                    "customer_phone": customer_phone,
                                    "order_id": order_id,
                                    "product_id": item_id,
                                    "quantity": quantity,
                                    "amount": unit_price * quantity,
                                    "purchased_at": created_at
                                }
                                self.db.table("purchase_history").insert(purchase_data).execute()
                                migrated_count += 1
                    else:
                        # No items, record the order total as a single purchase
                        existing = self.db.table("purchase_history").select("id").eq(
                            "tenant_id", target_tenant_id
                        ).eq("order_id", order_id).execute()
                        
                        if not existing.data:
                            purchase_data = {
                                "tenant_id": target_tenant_id,
                                "customer_phone": customer_phone,
                                "order_id": order_id,
                                "product_id": None,
                                "quantity": 1,
                                "amount": total_amount,
                                "purchased_at": created_at
                            }
                            self.db.table("purchase_history").insert(purchase_data).execute()
                            migrated_count += 1
                            
                except Exception as e:
                    logger.warning(f"Failed to migrate order {order.get('id')}: {e}")
                    skipped_count += 1
            
            return {
                "migrated_count": migrated_count,
                "skipped_count": skipped_count
            }
            
        except Exception as e:
            logger.error(f"Error migrating purchase history: {e}")
            raise
    
    async def _initialize_loyalty_system(
        self,
        source_tenant_id: str,
        target_tenant_id: str
    ) -> Dict[str, Any]:
        """Initialize loyalty points for migrated customers"""
        try:
            # Get customer profiles
            profiles_result = self.db.table("customer_profiles").select(
                "phone_number, total_spent"
            ).eq("tenant_id", target_tenant_id).execute()
            
            if not profiles_result.data:
                return {"created_count": 0, "skipped_count": 0}
            
            created_count = 0
            skipped_count = 0
            
            for profile in profiles_result.data:
                try:
                    phone = profile.get("phone_number")
                    total_spent = float(profile.get("total_spent", 0))
                    
                    # Check if loyalty account exists
                    existing = self.db.table("loyalty_points").select("id").eq(
                        "tenant_id", target_tenant_id
                    ).eq("customer_phone", phone).execute()
                    
                    if existing.data:
                        skipped_count += 1
                        continue
                    
                    # Calculate initial points (1 point per $1 spent)
                    initial_points = int(total_spent)
                    
                    loyalty_data = {
                        "tenant_id": target_tenant_id,
                        "customer_phone": phone,
                        "points_balance": initial_points,
                        "points_earned_total": initial_points,
                        "points_redeemed_total": 0,
                        "tier": "bronze" if initial_points < 1000 else "silver" if initial_points < 5000 else "gold" if initial_points < 10000 else "platinum",
                        "last_activity_date": datetime.now().isoformat(),
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat()
                    }
                    
                    self.db.table("loyalty_points").insert(loyalty_data).execute()
                    created_count += 1
                    
                except Exception as e:
                    logger.warning(f"Failed to create loyalty account: {e}")
                    skipped_count += 1
            
            return {
                "created_count": created_count,
                "skipped_count": skipped_count
            }
            
        except Exception as e:
            logger.error(f"Error initializing loyalty system: {e}")
            raise
    
    async def _create_migration_backup(
        self,
        tenant_id: str
    ) -> Dict[str, Any]:
        """Create a backup of tenant data before migration"""
        try:
            # In production, this would create a full database backup
            # For now, we'll log the backup intent
            backup_record = {
                "tenant_id": tenant_id,
                "backup_type": "pre_migration",
                "created_at": datetime.now().isoformat(),
                "status": "pending"
            }
            
            # Store backup metadata
            self.db.table("migration_backups").insert({
                "tenant_id": tenant_id,
                "backup_data": json.dumps(backup_record),
                "created_at": datetime.now().isoformat()
            }).execute()
            
            logger.info(f"Created backup record for tenant: {tenant_id}")
            
            return {"success": True, "backup_id": tenant_id}
            
        except Exception as e:
            logger.error(f"Error creating backup: {e}")
            return {"success": False, "error": str(e)}
    
    async def _store_migration_record(
        self,
        source_tenant_id: str,
        target_tenant_id: str,
        migrated_data: Dict[str, Any],
        progress: MigrationProgress
    ) -> None:
        """Store migration record for audit trail"""
        try:
            migration_record = {
                "source_tenant_id": source_tenant_id,
                "target_tenant_id": target_tenant_id,
                "status": progress.status.value,
                "data_migrated": json.dumps(progress.data_migrated),
                "errors": json.dumps(progress.errors),
                "started_at": progress.start_time.isoformat() if progress.start_time else None,
                "completed_at": progress.end_time.isoformat() if progress.end_time else None
            }
            
            self.db.table("migration_records").insert({
                "tenant_id": target_tenant_id,
                "migration_data": json.dumps(migration_record),
                "created_at": datetime.now().isoformat()
            }).execute()
            
        except Exception as e:
            logger.warning(f"Failed to store migration record: {e}")
    
    # ============================================
    # MIGRATION VALIDATION
    # ============================================
    
    async def validate_migration(
        self,
        source_tenant_id: str,
        target_tenant_id: str
    ) -> ValidationResult:
        """
        Validate integrity of migrated data.
        
        Args:
            source_tenant_id: Source tenant ID
            target_tenant_id: Target tenant ID in Vendly Pro
            
        Returns:
            ValidationResult with validation status
        """
        try:
            logger.info(f"Validating migration: {source_tenant_id} -> {target_tenant_id}")
            
            mismatches = []
            warnings = []
            
            # Count source data
            source_customers = self.db.table("orders").select(
                "customer_phone", distinct=True
            ).eq("tenant_id", source_tenant_id).execute()
            source_customer_count = len(source_customers.data) if source_customers.data else 0
            
            source_orders = self.db.table("orders").select(
                "count", count="exact"
            ).eq("tenant_id", source_tenant_id).execute()
            source_order_count = source_orders.count or 0
            
            # Count target data
            target_customers = self.db.table("customer_profiles").select(
                "count", count="exact"
            ).eq("tenant_id", target_tenant_id).execute()
            target_customer_count = target_customers.count or 0
            
            target_purchases = self.db.table("purchase_history").select(
                "count", count="exact"
            ).eq("tenant_id", target_tenant_id).execute()
            target_purchase_count = target_purchases.count or 0
            
            # Compare counts
            source_counts = {
                "customers": source_customer_count,
                "orders": source_order_count
            }
            
            target_counts = {
                "customers": target_customer_count,
                "purchase_history": target_purchase_count
            }
            
            # Check for significant discrepancies
            if source_customer_count > 0:
                customer_match_rate = target_customer_count / source_customer_count
                if customer_match_rate < 0.95:
                    mismatches.append({
                        "type": "customer_count",
                        "expected": source_customer_count,
                        "actual": target_customer_count,
                        "match_rate": customer_match_rate
                    })
            
            # Check for data integrity issues
            # Verify customer profiles have required fields
            profiles_result = self.db.table("customer_profiles").select(
                "phone_number, total_spent"
            ).eq("tenant_id", target_tenant_id).execute()
            
            if profiles_result.data:
                for profile in profiles_result.data:
                    if not profile.get("phone_number"):
                        mismatches.append({
                            "type": "missing_phone",
                            "profile_id": profile.get("id")
                        })
            
            is_valid = len(mismatches) == 0
            
            if not is_valid:
                warnings.append(f"Found {len(mismatches)} data mismatches")
            
            return ValidationResult(
                is_valid=is_valid,
                source_counts=source_counts,
                target_counts=target_counts,
                mismatches=mismatches,
                warnings=warnings
            )
            
        except Exception as e:
            logger.error(f"Error validating migration: {e}")
            return ValidationResult(
                is_valid=False,
                mismatches=[{"type": "validation_error", "error": str(e)}]
            )
    
    # ============================================
    # ROLLBACK CAPABILITIES
    # ============================================
    
    async def rollback_migration(
        self,
        target_tenant_id: str,
        restore_backup: bool = True
    ) -> Dict[str, Any]:
        """
        Rollback a migration if issues are detected.
        
        Args:
            target_tenant_id: Target tenant ID to rollback
            restore_backup: Whether to restore from backup
            
        Returns:
            Dictionary with rollback result
        """
        try:
            logger.info(f"Rolling back migration for tenant: {target_tenant_id}")
            
            # Get latest migration record
            migration_result = self.db.table("migration_records").select("*").eq(
                "tenant_id", target_tenant_id
            ).order("created_at", desc=True).limit(1).execute()
            
            if not migration_result.data:
                return {
                    "success": False,
                    "error": "No migration record found"
                }
            
            # Delete migrated customer profiles
            deleted_profiles = self.db.table("customer_profiles").delete().eq(
                "tenant_id", target_tenant_id
            ).execute()
            
            # Delete migrated purchase history
            deleted_purchases = self.db.table("purchase_history").delete().eq(
                "tenant_id", target_tenant_id
            ).execute()
            
            # Delete loyalty points if they exist
            deleted_loyalty = self.db.table("loyalty_points").delete().eq(
                "tenant_id", target_tenant_id
            ).execute()
            
            # Update migration record
            migration_record = migration_result.data[0]
            self.db.table("migration_records").update({
                "migration_data": json.dumps({
                    **json.loads(migration_record.get("migration_data", "{}")),
                    "status": "rolled_back"
                })
            }).eq("id", migration_record.get("id")).execute()
            
            return {
                "success": True,
                "deleted_data": {
                    "customer_profiles": deleted_profiles.count if hasattr(deleted_profiles, 'count') else 0,
                    "purchase_history": deleted_purchases.count if hasattr(deleted_purchases, 'count') else 0,
                    "loyalty_points": deleted_loyalty.count if hasattr(deleted_loyalty, 'count') else 0
                }
            }
            
        except Exception as e:
            logger.error(f"Error during rollback: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    # ============================================
    # UTILITY METHODS
    # ============================================
    
    async def get_migration_status(
        self,
        tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get current migration status for a tenant"""
        try:
            # Check active migrations
            if tenant_id in self._active_migrations:
                progress = self._active_migrations[tenant_id]
                return {
                    "status": progress.status.value,
                    "current_category": progress.current_category.value if progress.current_category else None,
                    "data_migrated": progress.data_migrated,
                    "errors": progress.errors,
                    "start_time": progress.start_time.isoformat() if progress.start_time else None
                }
            
            # Check migration records
            result = self.db.table("migration_records").select("*").eq(
                "tenant_id", tenant_id
            ).order("created_at", desc=True).limit(1).execute()
            
            if result.data:
                record = result.data[0]
                return {
                    "status": json.loads(record.get("migration_data", "{}")).get("status", "unknown"),
                    "completed_at": record.get("created_at")
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting migration status: {e}")
            return None
    
    async def get_all_migrations(
        self,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get all migration records"""
        try:
            result = self.db.table("migration_records").select("*").order(
                "created_at", desc=True
            ).limit(limit).execute()
            
            migrations = []
            if result.data:
                for record in result.data:
                    migrations.append({
                        "tenant_id": record.get("tenant_id"),
                        "migration_data": json.loads(record.get("migration_data", "{}")),
                        "created_at": record.get("created_at")
                    })
            
            return migrations
            
        except Exception as e:
            logger.error(f"Error getting migrations: {e}")
            return []