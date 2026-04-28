"""Admin web UI for tube-scout (008-admin-web-ui).

Thin Starlette layer over the existing CLI services. New analysis logic is
forbidden here per Constitution IV (CLI-First) — routes call services/...
functions only.
"""
