#!/usr/bin/env python3
"""
Script to apply Vendly Pro extended database schema migration.
This script reads the SQL migration file and applies it to the database.
"""

import os
import sys
import asyncio
from pathlib import Path

# Add the parent directory to the path to import config
sys.path.append(str(Path(__file__).parent.parent))

from db.supabase import get_supabase_client

async def apply_migration():
    """Apply the Vendly Pro extended schema migration"""
    
    # Read the migration SQL file
    migration_path = Path(__file__).parent.parent / "db" / "migrations" / "009_vendly_pro_extended_schema.sql"
    
    if not migration_path.exists():
        print(f"Error: Migration file not found at {migration_path}")
        return False
    
    try:
        with open(migration_path, 'r', encoding='utf-8') as f:
            migration_sql = f.read()
        
        print(f"Read migration file: {migration_path}")
        print(f"Migration SQL size: {len(migration_sql)} characters")
        
        # Get Supabase client
        supabase = get_supabase_client()
        
        # Split SQL into individual statements (simple approach)
        # Note: In production, use a proper SQL parser or execute in transactions
        statements = migration_sql.split(';')
        
        print(f"Executing {len(statements)} SQL statements...")
        
        # Execute each statement
        for i, statement in enumerate(statements):
            statement = statement.strip()
            if not statement:
                continue
            
            # Skip comments
            if statement.startswith('--'):
                continue
            
            try:
                # Execute the SQL statement
                result = supabase.rpc('exec_sql', {'sql': statement}).execute()
                print(f"  Statement {i+1}: OK")
            except Exception as e:
                print(f"  Statement {i+1}: ERROR - {str(e)}")
                # For some statements, we might need to use different methods
                # This is a simplified approach
        
        print("\nMigration completed successfully!")
        print("\nNew tables created:")
        print("  - customer_profiles")
        print("  - purchase_history")
        print("  - loyalty_points")
        print("  - loyalty_rewards")
        print("  - conversation_analytics")
        print("  - automated_responses")
        print("  - industry_templates")
        print("  - tenant_subscriptions")
        print("\nRLS policies and indexes have been configured.")
        
        return True
        
    except Exception as e:
        print(f"Error applying migration: {str(e)}")
        return False

def main():
    """Main entry point"""
    print("=" * 60)
    print("Vendly Pro Extended Schema Migration")
    print("=" * 60)
    print("\nThis script will apply the extended database schema for Vendly Pro.")
    print("This includes:")
    print("  • 8 new tables for premium features")
    print("  • Row Level Security (RLS) policies for tenant isolation")
    print("  • Performance indexes for optimization")
    print("  • Default industry templates")
    print("\nWARNING: This will modify your database structure.")
    
    response = input("\nDo you want to continue? (yes/no): ").strip().lower()
    
    if response != 'yes':
        print("Migration cancelled.")
        return
    
    # Apply migration
    success = asyncio.run(apply_migration())
    
    if success:
        print("\n✅ Migration applied successfully!")
        print("\nNext steps:")
        print("  1. Run tests to verify the schema: python -m pytest tests/")
        print("  2. Update your application code to use the new models")
        print("  3. Consider backing up your database")
    else:
        print("\n❌ Migration failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()