"""Shared pytest configuration for the backend suites.

Programme 01 (B-006) added per-account order limits (rate, open unpaid orders, duplicate-submission window). Many suites written
before them place dozens of orders for ONE test account within seconds, which those limits would (correctly) refuse. For the test
process only, the limits are raised here unless a suite sets its own values. Production defaults are unchanged
(order_protection.DEFAULTS); tests/test_programme01_order_protection.py runs the limits at exactly those defaults.
"""
import os

os.environ.setdefault("ORDER_OPEN_UNPAID_MAX", "100000")
os.environ.setdefault("ORDER_CREATE_PER_USER_10MIN", "100000")
os.environ.setdefault("ORDER_CREATE_PER_IP_10MIN", "100000")
os.environ.setdefault("ORDER_SUBMIT_WINDOW_SECONDS", "0")
