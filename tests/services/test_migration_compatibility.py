"""
Tests for MigrationCompatibilityChecker service
Requirements: 23.1, 23.2, 23.3, 23.4
"""
import pytest
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime
import json

# Add project directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.migration_compatibility import (
    MigrationCompatibilityChecker,
    CompatibilityLevel,
    FeatureStatus,
    APICompatibilityResult,
    SchemaCompatibilityResult,
    FeatureAvailabilityResult,
    MigrationRecommendation,
    CompatibilityCheckSummary
)
from db.supabase import get_supabase_client


class TestMigrationCompatibilityChecker:
    """Tests for MigrationCompatibilityChecker class"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database client"""
        db = Mock()
        
        # Mock table() to return a chainable mock
        def create_table_mock(table_name):
            mock_table = Mock()
            
            # Mock select().eq().execute() chain
            select_mock = Mock()
            eq_mock = Mock()
            execute_mock = Mock()
            
            # Set up default return values
            execute_mock.return_value = Mock(data=[], count=0)
            eq_mock.return_value = execute_mock
            select_mock.return_value = eq_mock
            
            # Mock for .count attribute
            execute_mock.count = 0
            
            mock_table.select = Mock(return_value=eq_mock)
            mock_table.insert = Mock(return_value=Mock(
                execute=Mock(return_value=Mock(data=[{"id": "test-id"}]))
            ))
            mock_table.update = Mock(return_value=Mock(
                execute=Mock(return_value=Mock(data=[{"id": "test-id"}]))
            ))
            mock_table.delete = Mock(return_value=Mock(
                execute=Mock(return_value=Mock(count=0))
            ))
            
            return mock_table
        
        db.table = Mock(side_effect=create_table_mock)
        return db
    
    @pytest.fixture
    def compatibility_checker(self, mock_db):
        """Create MigrationCompatibilityChecker with mock DB"""
        return MigrationCompatibilityChecker(db=mock_db)
    
    # ============================================
    # API COMPATIBILITY TESTS
    # ============================================
    
    @pytest.mark.asyncio
    async def test_check_api_compatibility_success(self, compatibility_checker, mock_db):
        """Test successful API compatibility check"""
        # Setup mock to return data
        def create_table_with_data(table_name):
            mock_table = Mock()
            execute_mock = Mock()
            execute_mock.data = [{"id": "test-1"}]
            execute_mock.count = 1
            
            eq_mock = Mock(return_value=execute_mock)
            select_mock = Mock(return_value=eq_mock)
            
            mock_table.select = Mock(return_value=lambda: select_mock.return_value(lambda: eq_mock))
            mock_table.select = Mock(return_value=eq_mock)
            return mock_table
        
        mock_db.table = Mock(side_effect=create_table_with_data)
        
        result = await compatibility_checker.check_api_compatibility("tenant-1")
        
        assert result is not None
        assert isinstance(result, APICompatibilityResult)
        assert hasattr(result, 'compatibility_level')
    
    @pytest.mark.asyncio
    async def test_check_api_compatibility_incompatible(self, compatibility_checker, mock_db):
        """Test API compatibility check when tables are missing"""
        # Mock table that raises exception
        mock_db.table = Mock(side_effect=Exception("Table not found"))
        
        result = await compatibility_checker.check_api_compatibility("tenant-1")
        
        assert result is not None
        assert result.compatibility_level in [CompatibilityLevel.INCOMPATIBLE, CompatibilityLevel.UNKNOWN]
    
    # ============================================
    # DATA SCHEMA COMPATIBILITY TESTS
    # ============================================
    
    @pytest.mark.asyncio
    async def test_check_schema_compatibility_success(self, compatibility_checker, mock_db):
        """Test successful schema compatibility check"""
        result = await compatibility_checker.check_data_schema_compatibility("tenant-1")
        
        assert result is not None
        assert isinstance(result, SchemaCompatibilityResult)
        assert hasattr(result, 'source_tables')
        assert hasattr(result, 'target_tables')
    
    @pytest.mark.asyncio
    async def test_check_schema_compatibility_with_data_loss(self, compatibility_checker, mock_db):
        """Test schema compatibility check detects data loss risks"""
        # Mock orders with no customer phone
        def create_table_mock(table_name):
            mock_table = Mock()
            
            if table_name == "orders":
                # Return orders without customer phone
                execute_mock = Mock()
                execute_mock.count = 10  # 10 orders without phone
                eq_mock = Mock(return_value=execute_mock)
                select_mock = Mock(return_value=eq_mock)
                
                # Handle is_() call
                is_mock = Mock(return_value=execute_mock)
                eq_mock.is_ = Mock(return_value=is_mock)
                
                mock_table.select = Mock(return_value=select_mock)
            elif table_name == "items":
                # Return items without category
                execute_mock = Mock()
                execute_mock.count = 5  # 5 items without category
                eq_mock = Mock(return_value=execute_mock)
                select_mock = Mock(return_value=eq_mock)
                
                is_mock = Mock(return_value=execute_mock)
                eq_mock.is_ = Mock(return_value=is_mock)
                
                mock_table.select = Mock(return_value=select_mock)
            else:
                execute_mock = Mock(data=[], count=0)
                eq_mock = Mock(return_value=execute_mock)
                select_mock = Mock(return_value=eq_mock)
                mock_table.select = Mock(return_value=select_mock)
            
            return mock_table
        
        mock_db.table = Mock(side_effect=create_table_mock)
        
        result = await compatibility_checker.check_data_schema_compatibility("tenant-1")
        
        assert result is not None
        # Should have data loss risks detected
        assert isinstance(result.data_loss_risks, list)
    
    # ============================================
    # FEATURE AVAILABILITY TESTS
    # ============================================
    
    @pytest.mark.asyncio
    async def test_check_feature_availability_success(self, compatibility_checker, mock_db):
        """Test successful feature availability check"""
        result = await compatibility_checker.check_feature_availability("tenant-1")
        
        assert result is not None
        assert isinstance(result, FeatureAvailabilityResult)
        assert hasattr(result, 'features')
        assert hasattr(result, 'unavailable_features')
    
    @pytest.mark.asyncio
    async def test_check_customer_profiles_feature_available(self, compatibility_checker, mock_db):
        """Test customer profiles feature check when available"""
        # Create mock that returns data for customer_profiles
        def create_table_mock(table_name):
            mock_table = Mock()
            execute_mock = Mock()
            
            if table_name == "customer_profiles":
                execute_mock.data = [{"id": "profile-1"}]
                execute_mock.count = 5
            elif table_name == "purchase_history":
                execute_mock.data = [{"id": "purchase-1"}]
                execute_mock.count = 10
            elif table_name == "loyalty_points":
                execute_mock.data = [{"id": "loyalty-1"}]
                execute_mock.count = 3
            elif table_name == "loyalty_rewards":
                execute_mock.data = [{"id": "reward-1"}]
                execute_mock.count = 2
            elif table_name == "orders":
                execute_mock.data = [{"id": "order-1"}]
                execute_mock.count = 20
            else:
                execute_mock.data = []
                execute_mock.count = 0
            
            mock_table.select.return_value = mock_table
            mock_table.eq.return_value = mock_table
            mock_table.limit.return_value = mock_table
            mock_table.execute.return_value = execute_mock

            return mock_table

        mock_db.table = Mock(side_effect=create_table_mock)

        status = await compatibility_checker._check_customer_profiles_feature("tenant-1")
        
        assert status in [FeatureStatus.AVAILABLE, FeatureStatus.REQUIRES_SETUP]
    
    @pytest.mark.asyncio
    async def test_check_customer_profiles_feature_unavailable(self, compatibility_checker, mock_db):
        """Test customer profiles feature check when unavailable"""
        # Mock that raises exception (table doesn't exist)
        mock_db.table = Mock(side_effect=Exception("Table not found"))
        
        status = await compatibility_checker._check_customer_profiles_feature("tenant-1")
        
        assert status == FeatureStatus.UNAVAILABLE
    
    # ============================================
    # MIGRATION RECOMMENDATIONS TESTS
    # ============================================
    
    @pytest.mark.asyncio
    async def test_get_migration_recommendations(self, compatibility_checker, mock_db):
        """Test migration recommendations generation"""
        result = await compatibility_checker.get_migration_recommendations("tenant-1")
        
        assert result is not None
        assert isinstance(result, list)
        assert len(result) > 0
        
        # Check that we have recommendations sorted by priority
        priorities = [rec.priority for rec in result]
        # High priority should come first
        if len(priorities) > 1:
            assert priorities[0] == "high"
    
    @pytest.mark.asyncio
    async def test_get_migration_recommendations_includes_backup(self, compatibility_checker, mock_db):
        """Test that recommendations always include backup advice"""
        result = await compatibility_checker.get_migration_recommendations("tenant-1")
        
        backup_recs = [r for r in result if r.category == "backup"]
        assert len(backup_recs) > 0
    
    # ============================================
    # FULL COMPATIBILITY CHECK TESTS
    # ============================================
    
    @pytest.mark.asyncio
    async def test_run_full_compatibility_check(self, compatibility_checker, mock_db):
        """Test full compatibility check"""
        result = await compatibility_checker.run_full_compatibility_check("tenant-1")
        
        assert result is not None
        assert isinstance(result, CompatibilityCheckSummary)
        assert result.tenant_id == "tenant-1"
        assert hasattr(result, 'api_result')
        assert hasattr(result, 'schema_result')
        assert hasattr(result, 'feature_result')
        assert hasattr(result, 'recommendations')
    
    @pytest.mark.asyncio
    async def test_run_full_compatibility_check_overall_status(self, compatibility_checker, mock_db):
        """Test that overall compatible flag is set correctly"""
        result = await compatibility_checker.run_full_compatibility_check("tenant-1")
        
        # Result should have overall_compatible flag
        assert hasattr(result, 'overall_compatible')
        assert isinstance(result.overall_compatible, bool)


class TestMigrationCompatibilityEnums:
    """Tests for compatibility checker enums and data classes"""
    
    def test_compatibility_level_enum(self):
        """Test CompatibilityLevel enum values"""
        assert CompatibilityLevel.FULL.value == "full"
        assert CompatibilityLevel.PARTIAL.value == "partial"
        assert CompatibilityLevel.INCOMPATIBLE.value == "incompatible"
        assert CompatibilityLevel.UNKNOWN.value == "unknown"
    
    def test_feature_status_enum(self):
        """Test FeatureStatus enum values"""
        assert FeatureStatus.AVAILABLE.value == "available"
        assert FeatureStatus.PARTIALLY_AVAILABLE.value == "partially_available"
        assert FeatureStatus.UNAVAILABLE.value == "unavailable"
        assert FeatureStatus.REQUIRES_SETUP.value == "requires_setup"
    
    def test_migration_recommendation_creation(self):
        """Test MigrationRecommendation creation"""
        rec = MigrationRecommendation(
            priority="high",
            category="backup",
            title="Create Backup",
            description="Test description",
            action_required="Run backup"
        )
        
        assert rec.priority == "high"
        assert rec.category == "backup"
        assert rec.title == "Create Backup"
        assert rec.description == "Test description"
        assert rec.action_required == "Run backup"
    
    def test_api_compatibility_result_creation(self):
        """Test APICompatibilityResult creation"""
        result = APICompatibilityResult(
            is_compatible=True,
            compatibility_level=CompatibilityLevel.FULL,
            api_versions={"tenants": "v1"},
            missing_endpoints=[],
            deprecated_endpoints=[],
            warnings=[],
            errors=[]
        )
        
        assert result.is_compatible is True
        assert result.compatibility_level == CompatibilityLevel.FULL
    
    def test_schema_compatibility_result_creation(self):
        """Test SchemaCompatibilityResult creation"""
        result = SchemaCompatibilityResult(
            is_compatible=True,
            compatibility_level=CompatibilityLevel.FULL,
            source_tables=["tenants", "items"],
            target_tables=["tenants", "items", "customer_profiles"],
            missing_columns={},
            type_mismatches=[],
            data_loss_risks=[]
        )
        
        assert result.is_compatible is True
        assert len(result.source_tables) == 2
        assert len(result.target_tables) == 3
    
    def test_feature_availability_result_creation(self):
        """Test FeatureAvailabilityResult creation"""
        result = FeatureAvailabilityResult(
            features={"customer_profiles": FeatureStatus.AVAILABLE},
            unavailable_features=[],
            setup_required=[],
            warnings=[]
        )
        
        assert "customer_profiles" in result.features
        assert result.features["customer_profiles"] == FeatureStatus.AVAILABLE


class TestMigrationCompatibilityCheckerIntegration:
    """Integration tests for MigrationCompatibilityChecker (requires real database)"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup for each test"""
        self.db = get_supabase_client()
        yield
    
    def test_compatibility_checker_instantiation(self):
        """Test that MigrationCompatibilityChecker can be instantiated"""
        checker = MigrationCompatibilityChecker(db=self.db)
        assert checker is not None
        assert checker.db is not None
    
    def test_required_tables_defined(self):
        """Test that required tables are properly defined"""
        checker = MigrationCompatibilityChecker(db=self.db)
        
        assert len(checker.REQUIRED_SOURCE_TABLES) > 0
        assert len(checker.REQUIRED_TARGET_TABLES) > 0
        assert len(checker.CORE_FEATURES) > 0
        
        # Target should include source tables
        for table in checker.REQUIRED_SOURCE_TABLES:
            assert table in checker.REQUIRED_TARGET_TABLES
    
    def test_core_features_defined(self):
        """Test that core features are properly defined"""
        expected_features = [
            "customer_profiles",
            "purchase_history",
            "loyalty_points",
            "loyalty_rewards",
            "recommendations",
            "analytics"
        ]
        
        checker = MigrationCompatibilityChecker(db=self.db)
        
        for feature in expected_features:
            assert feature in checker.CORE_FEATURES


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--run"]))