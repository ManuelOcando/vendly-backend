"""
Migration Compatibility Checker for Vendly Pro
Validates API compatibility, data schema compatibility, and feature availability for migration.
"""
from typing import Dict, Any, List, Optional
import logging
from dataclasses import dataclass, field
from enum import Enum

from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)


class CompatibilityLevel(str, Enum):
    """Level of compatibility found during migration check"""
    FULL = "full"
    PARTIAL = "partial"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


class FeatureStatus(str, Enum):
    """Status of feature availability"""
    AVAILABLE = "available"
    PARTIALLY_AVAILABLE = "partially_available"
    UNAVAILABLE = "unavailable"
    REQUIRES_SETUP = "requires_setup"


@dataclass
class APICompatibilityResult:
    """Result of API compatibility check"""
    is_compatible: bool
    compatibility_level: CompatibilityLevel
    api_versions: Dict[str, str] = field(default_factory=dict)
    missing_endpoints: List[str] = field(default_factory=list)
    deprecated_endpoints: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class SchemaCompatibilityResult:
    """Result of data schema compatibility check"""
    is_compatible: bool
    compatibility_level: CompatibilityLevel
    source_tables: List[str] = field(default_factory=list)
    target_tables: List[str] = field(default_factory=list)
    missing_columns: Dict[str, List[str]] = field(default_factory=dict)
    type_mismatches: List[Dict[str, Any]] = field(default_factory=list)
    data_loss_risks: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class FeatureAvailabilityResult:
    """Result of feature availability check"""
    features: Dict[str, FeatureStatus] = field(default_factory=dict)
    unavailable_features: List[str] = field(default_factory=list)
    setup_required: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class MigrationRecommendation:
    """Recommendation for migration"""
    priority: str  # high, medium, low
    category: str
    title: str
    description: str
    action_required: Optional[str] = None


@dataclass
class CompatibilityCheckSummary:
    """Summary of all compatibility checks"""
    tenant_id: str
    overall_compatible: bool
    api_result: Optional[APICompatibilityResult] = None
    schema_result: Optional[SchemaCompatibilityResult] = None
    feature_result: Optional[FeatureAvailabilityResult] = None
    recommendations: List[MigrationRecommendation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class MigrationCompatibilityChecker:
    """
    Service for checking compatibility between current Vendly and Vendly Pro.
    
    Validates:
    - API endpoint compatibility
    - Data schema compatibility  
    - Feature availability
    - Provides migration recommendations
    """
    
    # Required tables in Vendly (source)
    REQUIRED_SOURCE_TABLES = [
        "tenants",
        "items", 
        "categories",
        "orders",
        "order_items",
        "whatsapp_configs"
    ]
    
    # Required tables in Vendly Pro (target)
    REQUIRED_TARGET_TABLES = [
        "tenants",
        "items",
        "categories", 
        "orders",
        "order_items",
        "whatsapp_configs",
        "customer_profiles",
        "purchase_history",
        "loyalty_points",
        "loyalty_rewards"
    ]
    
    # Core features that must be available
    CORE_FEATURES = [
        "customer_profiles",
        "purchase_history", 
        "loyalty_points",
        "loyalty_rewards",
        "recommendations",
        "analytics"
    ]
    
    # Tables that need migration
    MIGRATION_TABLES = [
        "tenants",
        "items",
        "categories",
        "orders",
        "order_items",
        "whatsapp_configs"
    ]
    
    def __init__(self, db=None):
        self.db = db or get_supabase_client()
    
    # ============================================
    # API COMPATIBILITY CHECKS
    # ============================================
    
    async def check_api_compatibility(
        self, 
        tenant_id: str
    ) -> APICompatibilityResult:
        """
        Check API compatibility between current Vendly and Vendly Pro.
        
        Validates that all required API endpoints are available and compatible.
        
        Args:
            tenant_id: Tenant identifier to check
            
        Returns:
            APICompatibilityResult with compatibility assessment
        """
        try:
            logger.info(f"Checking API compatibility for tenant: {tenant_id}")
            
            warnings = []
            errors = []
            missing_endpoints = []
            deprecated_endpoints = []
            api_versions = {}
            
            # Check core database tables exist and are accessible
            tables_to_check = [
                ("tenants", "tenant management"),
                ("items", "product management"),
                ("orders", "order management"),
                ("categories", "category management")
            ]
            
            for table_name, feature in tables_to_check:
                try:
                    result = self.db.table(table_name).select(
                        "id", count="exact"
                    ).eq("tenant_id", tenant_id).execute()
                    
                    api_versions[table_name] = "v1"
                    
                except Exception as e:
                    error_msg = f"Table {table_name} not accessible: {str(e)}"
                    errors.append(error_msg)
                    logger.warning(error_msg)
            
            # Check if new Vendly Pro tables are available
            new_tables = ["customer_profiles", "purchase_history", "loyalty_points"]
            for table_name in new_tables:
                try:
                    result = self.db.table(table_name).select(
                        "id", count="exact"
                    ).limit(1).execute()
                    api_versions[table_name] = "v2"
                except Exception as e:
                    warning_msg = f"New table {table_name} not available: {str(e)}"
                    warnings.append(warning_msg)
                    logger.info(warning_msg)
            
            # Determine compatibility level
            if len(errors) > 0:
                compatibility_level = CompatibilityLevel.INCOMPATIBLE
                is_compatible = False
            elif len(warnings) > 0:
                compatibility_level = CompatibilityLevel.PARTIAL
                is_compatible = True
            else:
                compatibility_level = CompatibilityLevel.FULL
                is_compatible = True
            
            # Check for deprecated endpoints/features
            # Legacy WhatsApp config structure check
            try:
                whatsapp_result = self.db.table("whatsapp_configs").select("*").eq(
                    "tenant_id", tenant_id
                ).execute()
                
                if whatsapp_result.data:
                    config = whatsapp_result.data[0]
                    if "instance_id" not in config and "phone_number_id" not in config:
                        deprecated_endpoints.append("whatsapp_configs:legacy_format")
                        warnings.append("WhatsApp config uses legacy format - migration recommended")
                        
            except Exception as e:
                warnings.append(f"Could not check WhatsApp config: {str(e)}")
            
            return APICompatibilityResult(
                is_compatible=is_compatible,
                compatibility_level=compatibility_level,
                api_versions=api_versions,
                missing_endpoints=missing_endpoints,
                deprecated_endpoints=deprecated_endpoints,
                warnings=warnings,
                errors=errors
            )
            
        except Exception as e:
            logger.error(f"Error checking API compatibility: {e}")
            return APICompatibilityResult(
                is_compatible=False,
                compatibility_level=CompatibilityLevel.UNKNOWN,
                errors=[f"Error during check: {str(e)}"]
            )
    
    # ============================================
    # DATA SCHEMA COMPATIBILITY CHECKS
    # ============================================
    
    async def check_data_schema_compatibility(
        self, 
        tenant_id: str
    ) -> SchemaCompatibilityResult:
        """
        Check data schema compatibility between source and target.
        
        Validates that source data can be migrated to target schema without loss.
        
        Args:
            tenant_id: Tenant identifier to check
            
        Returns:
            SchemaCompatibilityResult with schema compatibility assessment
        """
        try:
            logger.info(f"Checking data schema compatibility for tenant: {tenant_id}")
            
            source_tables = []
            target_tables = []
            missing_columns = {}
            type_mismatches = []
            data_loss_risks = []
            
            # Get source tables (current Vendly)
            for table_name in self.REQUIRED_SOURCE_TABLES:
                try:
                    result = self.db.table(table_name).select("*").limit(1).execute()
                    if result.data is not None:
                        source_tables.append(table_name)
                except Exception as e:
                    logger.warning(f"Source table {table_name} not found: {e}")
            
            # Get target tables (Vendly Pro)
            for table_name in self.REQUIRED_TARGET_TABLES:
                try:
                    result = self.db.table(table_name).select("*").limit(1).execute()
                    if result.data is not None:
                        target_tables.append(table_name)
                except Exception as e:
                    logger.warning(f"Target table {table_name} not available: {e}")
            
            # Check for missing columns in target
            schema_checks = {
                "items": ["name", "price", "tenant_id"],
                "orders": ["tenant_id", "customer_phone", "total_amount", "status"],
                "order_items": ["order_id", "item_id", "quantity"]
            }
            
            for table_name, required_columns in schema_checks.items():
                if table_name in target_tables:
                    try:
                        # Sample a row to check columns
                        result = self.db.table(table_name).select("*").limit(1).execute()
                        if result.data:
                            existing_columns = set(result.data[0].keys())
                            for col in required_columns:
                                if col not in existing_columns:
                                    if table_name not in missing_columns:
                                        missing_columns[table_name] = []
                                    missing_columns[table_name].append(col)
                    except Exception as e:
                        logger.warning(f"Could not check columns for {table_name}: {e}")
            
            # Check for data that might be lost during migration
            # Check for orders without customer phone (will be skipped in migration)
            try:
                orders_no_phone = self.db.table("orders").select(
                    "id", count="exact"
                ).eq("tenant_id", tenant_id).is_("customer_phone", "null").execute()
                
                if orders_no_phone.count and orders_no_phone.count > 0:
                    data_loss_risks.append({
                        "table": "orders",
                        "column": "customer_phone",
                        "affected_rows": orders_no_phone.count,
                        "risk": "Orders without customer phone will not create customer profiles"
                    })
            except Exception as e:
                logger.warning(f"Could not check orders data: {e}")
            
            # Check for items without category (warning)
            try:
                items_no_category = self.db.table("items").select(
                    "id", count="exact"
                ).eq("tenant_id", tenant_id).is_("category_id", "null").execute()
                
                if items_no_category.count and items_no_category.count > 0:
                    data_loss_risks.append({
                        "table": "items",
                        "column": "category_id", 
                        "affected_rows": items_no_category.count,
                        "risk": "Items without category will lose categorization in migration",
                        "severity": "low"
                    })
            except Exception as e:
                logger.warning(f"Could not check items data: {e}")
            
            # Determine compatibility level
            critical_missing = sum(len(cols) for cols in missing_columns.values())
            high_risks = [
                r for r in data_loss_risks 
                if r.get("severity") != "low"
            ]
            
            if critical_missing > 0 or len(high_risks) > 3:
                compatibility_level = CompatibilityLevel.INCOMPATIBLE
                is_compatible = False
            elif len(data_loss_risks) > 0:
                compatibility_level = CompatibilityLevel.PARTIAL
                is_compatible = True
            else:
                compatibility_level = CompatibilityLevel.FULL
                is_compatible = True
            
            return SchemaCompatibilityResult(
                is_compatible=is_compatible,
                compatibility_level=compatibility_level,
                source_tables=source_tables,
                target_tables=target_tables,
                missing_columns=missing_columns,
                type_mismatches=type_mismatches,
                data_loss_risks=data_loss_risks
            )
            
        except Exception as e:
            logger.error(f"Error checking schema compatibility: {e}")
            return SchemaCompatibilityResult(
                is_compatible=False,
                compatibility_level=CompatibilityLevel.UNKNOWN,
                data_loss_risks=[{"risk": f"Error during check: {str(e)}", "severity": "high"}]
            )
    
    # ============================================
    # FEATURE AVAILABILITY CHECKS
    # ============================================
    
    async def check_feature_availability(
        self, 
        tenant_id: str
    ) -> FeatureAvailabilityResult:
        """
        Check availability of Vendly Pro features for the tenant.
        
        Validates that all required features are available and properly configured.
        
        Args:
            tenant_id: Tenant identifier to check
            
        Returns:
            FeatureAvailabilityResult with feature availability assessment
        """
        try:
            logger.info(f"Checking feature availability for tenant: {tenant_id}")
            
            features = {}
            unavailable_features = []
            setup_required = []
            warnings = []
            
            # Check each core feature
            feature_checks = {
                "customer_profiles": self._check_customer_profiles_feature,
                "purchase_history": self._check_purchase_history_feature,
                "loyalty_points": self._check_loyalty_points_feature,
                "loyalty_rewards": self._check_loyalty_rewards_feature,
                "recommendations": self._check_recommendations_feature,
                "analytics": self._check_analytics_feature
            }
            
            for feature_name, check_func in feature_checks.items():
                try:
                    status = await check_func(tenant_id)
                    features[feature_name] = status
                    
                    if status == FeatureStatus.UNAVAILABLE:
                        unavailable_features.append(feature_name)
                    elif status == FeatureStatus.REQUIRES_SETUP:
                        setup_required.append(feature_name)
                        
                except Exception as e:
                    logger.warning(f"Error checking feature {feature_name}: {e}")
                    features[feature_name] = FeatureStatus.UNAVAILABLE
                    unavailable_features.append(feature_name)
            
            # Check for WhatsApp configuration
            try:
                whatsapp_result = self.db.table("whatsapp_configs").select("*").eq(
                    "tenant_id", tenant_id
                ).execute()
                
                if not whatsapp_result.data:
                    warnings.append("No WhatsApp configuration found - setup required")
                    setup_required.append("whatsapp")
                else:
                    features["whatsapp"] = FeatureStatus.AVAILABLE
                    
            except Exception as e:
                warnings.append(f"Could not check WhatsApp config: {str(e)}")
                features["whatsapp"] = FeatureStatus.UNAVAILABLE
            
            return FeatureAvailabilityResult(
                features=features,
                unavailable_features=unavailable_features,
                setup_required=setup_required,
                warnings=warnings
            )
            
        except Exception as e:
            logger.error(f"Error checking feature availability: {e}")
            return FeatureAvailabilityResult(
                features={},
                unavailable_features=list(self.CORE_FEATURES),
                warnings=[f"Error during check: {str(e)}"]
            )
    
    async def _check_customer_profiles_feature(self, tenant_id: str) -> FeatureStatus:
        """Check if customer profiles feature is available"""
        try:
            result = self.db.table("customer_profiles").select("id").limit(1).execute()
            if result.data is not None:
                # Check if tenant has any profiles
                count_result = self.db.table("customer_profiles").select(
                    "id", count="exact"
                ).eq("tenant_id", tenant_id).execute()
                
                if count_result.count and count_result.count > 0:
                    return FeatureStatus.AVAILABLE
                else:
                    return FeatureStatus.REQUIRES_SETUP  # Table exists but no data
            return FeatureStatus.UNAVAILABLE
        except Exception:
            return FeatureStatus.UNAVAILABLE
    
    async def _check_purchase_history_feature(self, tenant_id: str) -> FeatureStatus:
        """Check if purchase history feature is available"""
        try:
            result = self.db.table("purchase_history").select("id").limit(1).execute()
            if result.data is not None:
                count_result = self.db.table("purchase_history").select(
                    "id", count="exact"
                ).eq("tenant_id", tenant_id).execute()
                
                if count_result.count and count_result.count > 0:
                    return FeatureStatus.AVAILABLE
                else:
                    return FeatureStatus.REQUIRES_SETUP
            return FeatureStatus.UNAVAILABLE
        except Exception:
            return FeatureStatus.UNAVAILABLE
    
    async def _check_loyalty_points_feature(self, tenant_id: str) -> FeatureStatus:
        """Check if loyalty points feature is available"""
        try:
            result = self.db.table("loyalty_points").select("id").limit(1).execute()
            if result.data is not None:
                count_result = self.db.table("loyalty_points").select(
                    "id", count="exact"
                ).eq("tenant_id", tenant_id).execute()
                
                if count_result.count and count_result.count > 0:
                    return FeatureStatus.AVAILABLE
                else:
                    return FeatureStatus.REQUIRES_SETUP
            return FeatureStatus.UNAVAILABLE
        except Exception:
            return FeatureStatus.UNAVAILABLE
    
    async def _check_loyalty_rewards_feature(self, tenant_id: str) -> FeatureStatus:
        """Check if loyalty rewards feature is available"""
        try:
            result = self.db.table("loyalty_rewards").select("id").limit(1).execute()
            if result.data is not None:
                count_result = self.db.table("loyalty_rewards").select(
                    "id", count="exact"
                ).eq("tenant_id", tenant_id).execute()
                
                if count_result.count and count_result.count > 0:
                    return FeatureStatus.AVAILABLE
                else:
                    return FeatureStatus.REQUIRES_SETUP
            return FeatureStatus.UNAVAILABLE
        except Exception:
            return FeatureStatus.UNAVAILABLE
    
    async def _check_recommendations_feature(self, tenant_id: str) -> FeatureStatus:
        """Check if recommendations feature is available"""
        # Check if recommendation engine tables/functions exist
        try:
            # Check for recommendation data or RPC functions
            result = self.db.table("purchase_history").select(
                "id", count="exact"
            ).eq("tenant_id", tenant_id).execute()
            
            if result.count and result.count >= 10:  # Need enough data
                return FeatureStatus.AVAILABLE
            elif result.count and result.count > 0:
                return FeatureStatus.PARTIALLY_AVAILABLE
            else:
                return FeatureStatus.REQUIRES_SETUP
        except Exception:
            return FeatureStatus.UNAVAILABLE
    
    async def _check_analytics_feature(self, tenant_id: str) -> FeatureStatus:
        """Check if analytics feature is available"""
        try:
            # Check for orders to analyze
            result = self.db.table("orders").select(
                "id", count="exact"
            ).eq("tenant_id", tenant_id).execute()
            
            if result.count and result.count >= 10:
                return FeatureStatus.AVAILABLE
            elif result.count and result.count > 0:
                return FeatureStatus.PARTIALLY_AVAILABLE
            else:
                return FeatureStatus.REQUIRES_SETUP
        except Exception:
            return FeatureStatus.UNAVAILABLE
    
    # ============================================
    # MIGRATION RECOMMENDATIONS
    # ============================================
    
    async def get_migration_recommendations(
        self, 
        tenant_id: str
    ) -> List[MigrationRecommendation]:
        """
        Get migration recommendations based on compatibility checks.
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            List of MigrationRecommendation objects sorted by priority
        """
        try:
            logger.info(f"Generating migration recommendations for tenant: {tenant_id}")
            
            recommendations = []
            
            # Run all compatibility checks
            api_result = await self.check_api_compatibility(tenant_id)
            schema_result = await self.check_data_schema_compatibility(tenant_id)
            feature_result = await self.check_feature_availability(tenant_id)
            
            # Generate recommendations based on API compatibility
            if api_result.compatibility_level == CompatibilityLevel.INCOMPATIBLE:
                recommendations.append(MigrationRecommendation(
                    priority="high",
                    category="api",
                    title="Fix API Compatibility Issues",
                    description="Some required tables are not accessible. Migration cannot proceed.",
                    action_required="Ensure all source tables are available"
                ))
            
            if api_result.deprecated_endpoints:
                recommendations.append(MigrationRecommendation(
                    priority="medium",
                    category="api",
                    title="Update Deprecated Endpoints",
                    description=f"Found deprecated endpoints: {', '.join(api_result.deprecated_endpoints)}",
                    action_required="Update configuration before migration"
                ))
            
            # Generate recommendations based on schema compatibility
            if schema_result.data_loss_risks:
                for risk in schema_result.data_loss_risks:
                    severity = risk.get("severity", "medium")
                    recommendations.append(MigrationRecommendation(
                        priority="high" if severity != "low" else "medium",
                        category="data",
                        title=f"Data Loss Risk in {risk.get('table')}",
                        description=risk.get('risk', 'Unknown risk'),
                        action_required=f"Review {risk.get('affected_rows', 0)} affected rows"
                    ))
            
            if schema_result.missing_columns:
                recommendations.append(MigrationRecommendation(
                    priority="high",
                    category="schema",
                    title="Address Missing Columns",
                    description=f"Missing columns in: {', '.join(schema_result.missing_columns.keys())}",
                    action_required="Add required columns before migration"
                ))
            
            # Generate recommendations based on feature availability
            if feature_result.unavailable_features:
                recommendations.append(MigrationRecommendation(
                    priority="medium",
                    category="features",
                    title="Enable Unavailable Features",
                    description=f"Features not available: {', '.join(feature_result.unavailable_features)}",
                    action_required="Enable or configure missing features"
                ))
            
            if feature_result.setup_required:
                recommendations.append(MigrationRecommendation(
                    priority="low",
                    category="setup",
                    title="Feature Setup Required",
                    description=f"Features needing setup: {', '.join(feature_result.setup_required)}",
                    action_required="Initialize feature data after migration"
                ))
            
            # General recommendations
            recommendations.append(MigrationRecommendation(
                priority="high",
                category="backup",
                title="Create Backup Before Migration",
                description="Always create a backup before performing migration",
                action_required="Run backup process before migration"
            ))
            
            # Sort by priority
            priority_order = {"high": 0, "medium": 1, "low": 2}
            recommendations.sort(key=lambda x: priority_order.get(x.priority, 3))
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Error generating recommendations: {e}")
            return [
                MigrationRecommendation(
                    priority="high",
                    category="error",
                    title="Error Generating Recommendations",
                    description=str(e),
                    action_required="Review error and retry"
                )
            ]
    
    # ============================================
    # COMPREHENSIVE CHECK
    # ============================================
    
    async def run_full_compatibility_check(
        self, 
        tenant_id: str
    ) -> CompatibilityCheckSummary:
        """
        Run all compatibility checks and generate summary.
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            CompatibilityCheckSummary with all results
        """
        try:
            logger.info(f"Running full compatibility check for tenant: {tenant_id}")
            
            # Run all checks
            api_result = await self.check_api_compatibility(tenant_id)
            schema_result = await self.check_data_schema_compatibility(tenant_id)
            feature_result = await self.check_feature_availability(tenant_id)
            recommendations = await self.get_migration_recommendations(tenant_id)
            
            # Collect warnings and errors
            warnings = []
            errors = []
            
            warnings.extend(api_result.warnings)
            errors.extend(api_result.errors)
            
            if schema_result.data_loss_risks:
                warnings.extend([r.get("risk") for r in schema_result.data_loss_risks])
            
            warnings.extend(feature_result.warnings)
            
            # Determine overall compatibility
            overall_compatible = (
                api_result.is_compatible and 
                schema_result.is_compatible and
                len(feature_result.unavailable_features) == 0
            )
            
            return CompatibilityCheckSummary(
                tenant_id=tenant_id,
                overall_compatible=overall_compatible,
                api_result=api_result,
                schema_result=schema_result,
                feature_result=feature_result,
                recommendations=recommendations,
                warnings=warnings,
                errors=errors
            )
            
        except Exception as e:
            logger.error(f"Error running full compatibility check: {e}")
            return CompatibilityCheckSummary(
                tenant_id=tenant_id,
                overall_compatible=False,
                errors=[f"Error during check: {str(e)}"]
            )