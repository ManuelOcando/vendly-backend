#!/bin/bash
# Keep-alive script for Evolution API on Render
# Run this every 5 minutes via cron or scheduler

curl -s -o /dev/null -w "%{http_code}" https://vendly-evolution.onrender.com/health
