"""
The columns this backend expects each table to have. Generated, not hand-written.

Regenerate after every migration:

    python scripts/audit_schema_usage.py --emit-schema

Two consumers, one source of truth:

* `db/schema_check.py` compares this against the live database at startup and
  logs whatever is missing, so a migration that never reached an environment is
  visible in that environment's boot log instead of surfacing weeks later as a
  feature that quietly does nothing.
* `tests/fake_supabase.py` validates column names against it, so a query naming
  a column that does not exist fails in the test suite rather than in production.

The second one is the point. Until now the test doubles modelled the shape of
the query builder and not the schema of the database, so a query could be
structurally valid and semantically impossible - `select("count")`,
`orders.total_amount`, `categories.order` - and 618 tests would still pass. An
audit on 2026-07-27 found 41 such queries, every one of them inside a try/except
that turned a schema error into a silently missing feature.
"""

EXPECTED_SCHEMA = {
    "alert_configs": (
        "id", "tenant_id", "alert_type", "enabled", "threshold",
        "notification_phone", "last_triggered", "created_at",
        "updated_at"
    ),
    "alert_logs": (
        "id", "tenant_id", "seller_phone", "alert_type", "message",
        "sent_at", "status"
    ),
    "appointments": (
        "id", "tenant_id", "customer_phone", "item_id",
        "professional_name", "scheduled_at", "duration_minutes",
        "status", "cancellation_reason", "reminder_24h_sent_at",
        "reminder_1h_sent_at", "created_at", "updated_at"
    ),
    "automated_distribution_rules": (
        "id", "tenant_id", "rule_name", "rule_type", "description",
        "coupon_template_id", "coupon_type", "discount_type",
        "discount_value", "trigger_conditions", "distribution_schedule",
        "status", "is_recurring", "max_distributions_per_customer",
        "total_distributions", "last_distribution_date", "created_at",
        "updated_at"
    ),
    "automated_responses": (
        "id", "tenant_id", "question_pattern", "response_text",
        "examples", "usage_count", "success_rate", "is_active",
        "created_by", "created_at", "updated_at"
    ),
    "bot_configurations": (
        "id", "tenant_id", "business_hours", "auto_reply_enabled",
        "payment_info", "welcome_message", "order_confirmation_message",
        "payment_instructions", "out_of_hours_message", "created_at",
        "updated_at", "cancellation_policy_hours", "timezone",
        "bot_paused", "last_seller_activity_at", "default_language"
    ),
    "business_hours_exceptions": (
        "id", "tenant_id", "exception_date", "is_closed", "open_time",
        "close_time", "created_at"
    ),
    "cart_items": (
        "id", "cart_id", "tenant_id", "item_id", "quantity",
        "unit_price", "created_at"
    ),
    "carts": (
        "id", "tenant_id", "customer_id", "status", "source",
        "customer_phone", "total", "expires_at", "created_at",
        "updated_at"
    ),
    "categories": (
        "id", "tenant_id", "name", "slug", "description", "image_url",
        "sort_order", "is_active", "created_at"
    ),
    "conversation_analytics": (
        "id", "tenant_id", "customer_phone", "message_type", "topic",
        "sentiment_score", "response_time_seconds", "resolved",
        "conversation_date", "created_at"
    ),
    "conversation_sessions": (
        "id", "tenant_id", "customer_phone", "current_state", "cart_id",
        "session_data", "last_message_at", "expires_at", "created_at",
        "updated_at"
    ),
    "conversations": (
        "id", "tenant_id", "customer_id", "phone", "is_vendor",
        "status", "bot_state", "bot_context", "cart_id",
        "last_message_at", "created_at"
    ),
    "coupon_redemptions": (
        "id", "tenant_id", "coupon_id", "customer_phone", "order_id",
        "discount_applied", "original_order_amount",
        "final_order_amount", "redeemed_at"
    ),
    "coupons": (
        "id", "tenant_id", "coupon_code", "coupon_type", "description",
        "discount_type", "discount_value", "min_purchase_amount",
        "max_discount_amount", "valid_from", "valid_until",
        "usage_limit", "usage_count", "status", "created_by",
        "created_at", "updated_at"
    ),
    "customer_profiles": (
        "id", "tenant_id", "phone_number", "preferences", "allergies",
        "dietary_restrictions", "favorite_products", "total_spent",
        "last_purchase_date", "created_at", "updated_at"
    ),
    "customers": (
        "id", "tenant_id", "phone", "name", "email", "total_orders",
        "total_spent", "created_at", "updated_at"
    ),
    "distribution_logs": (
        "id", "tenant_id", "rule_id", "customer_phone", "coupon_id",
        "distribution_type", "trigger_data", "status", "error_message",
        "distributed_at"
    ),
    "industry_templates": (
        "id", "industry", "name", "configuration", "default_categories",
        "default_messages", "workflow_templates", "created_at",
        "updated_at"
    ),
    "items": (
        "id", "tenant_id", "category_id", "type", "name", "description",
        "price", "currency", "images", "stock_quantity",
        "low_stock_threshold", "track_stock",
        "service_duration_minutes", "is_active", "is_featured",
        "metadata", "search_text", "total_sold", "likes_count",
        "created_at", "updated_at"
    ),
    "loyalty_points": (
        "id", "tenant_id", "customer_phone", "points_balance",
        "points_earned_total", "points_redeemed_total", "tier",
        "last_activity_date", "created_at", "updated_at"
    ),
    "loyalty_rewards": (
        "id", "tenant_id", "name", "description", "points_required",
        "reward_type", "reward_value", "is_active", "created_at",
        "updated_at"
    ),
    "messages": (
        "id", "conversation_id", "tenant_id", "role", "content",
        "media_url", "media_type", "created_at"
    ),
    "migration_backups": (
        "id", "tenant_id", "backup_data", "created_at"
    ),
    "migration_records": (
        "id", "tenant_id", "migration_data", "created_at"
    ),
    "offline_messages": (
        "id", "tenant_id", "customer_phone", "message", "created_at",
        "notified_at"
    ),
    "order_items": (
        "id", "tenant_id", "order_id", "item_id", "item_name",
        "quantity", "unit_price", "subtotal", "created_at"
    ),
    "orders": (
        "id", "tenant_id", "cart_id", "customer_id", "order_number",
        "status", "payment_method", "payment_reference",
        "payment_proof_url", "subtotal", "total", "customer_phone",
        "customer_name", "delivery_notes", "created_at", "updated_at"
    ),
    "post_sale_requests": (
        "id", "tenant_id", "customer_phone", "order_id", "request_type",
        "description", "status", "satisfaction_rating", "created_at",
        "updated_at", "resolved_at"
    ),
    "purchase_history": (
        "id", "tenant_id", "customer_phone", "order_id", "product_id",
        "quantity", "amount", "purchased_at"
    ),
    "recommendation_interactions": (
        "id", "tenant_id", "customer_phone", "recommendation_id",
        "product_id", "recommendation_type", "interaction_type",
        "timestamp", "session_id", "context"
    ),
    "remarketing_campaigns": (
        "id", "tenant_id", "campaign_type", "target_audience",
        "message_template", "offer_code", "status", "created_at",
        "updated_at"
    ),
    "remarketing_notifications": (
        "id", "tenant_id", "customer_phone", "product_id", "status",
        "created_at"
    ),
    "remarketing_reminders": (
        "id", "tenant_id", "customer_phone", "reminder_type",
        "offer_code", "status", "created_at"
    ),
    "remarketing_suggestions": (
        "id", "tenant_id", "customer_phone", "order_id", "status",
        "created_at"
    ),
    "schema_migrations": (
        "filename", "applied_at"
    ),
    "subscriptions": (
        "id", "tenant_id", "plan", "status", "payment_method",
        "payment_reference", "amount", "started_at", "expires_at",
        "created_at"
    ),
    "tenant_subscriptions": (
        "id", "tenant_id", "plan_type", "features", "limits",
        "current_period_start", "current_period_end", "status",
        "created_at", "updated_at"
    ),
    "tenants": (
        "id", "owner_id", "name", "slug", "type", "description",
        "logo_url", "whatsapp_number", "whatsapp_provider",
        "whatsapp_instance_id", "whatsapp_connected", "bot_enabled",
        "bot_personality", "bot_schedule", "payment_config",
        "store_config", "subscription_plan", "subscription_expires_at",
        "created_at", "updated_at", "onboarding_status",
        "bot_personality_preset"
    ),
    "time_slots": (
        "id", "tenant_id", "date", "start_time", "end_time",
        "is_available", "is_recurring", "created_at"
    ),
    "user_legal_acceptance": (
        "id", "user_id", "accepted_privacy_policy",
        "accepted_terms_of_service", "privacy_policy_version",
        "terms_version", "ip_address", "user_agent", "accepted_at",
        "created_at", "updated_at"
    ),
    "whatsapp_configs": (
        "id", "tenant_id", "phone_number", "is_connected",
        "business_hours_start", "business_hours_end", "welcome_message",
        "auto_reply_enabled", "created_at", "updated_at",
        "phone_number_id", "access_token", "business_account_id",
        "provider", "seller_phone"
    ),
    "whatsapp_messages": (
        "id", "tenant_id", "direction", "sender_phone",
        "receiver_phone", "content", "message_type", "status",
        "created_at"
    ),
}


def columns_for(table: str) -> frozenset:
    """Known columns for a table, or an empty set if it is not in the map."""
    return frozenset(EXPECTED_SCHEMA.get(table, ()))


def known_table(table: str) -> bool:
    return table in EXPECTED_SCHEMA
