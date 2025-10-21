# Ops Center Billing - Quick Start Guide

## 🚀 Current Status: READY

### ✅ What's Working

- **API Endpoints**: All billing endpoints registered and responding
- **Stripe Integration**: Configured with test keys
- **Lago Integration**: Connected to Lago API v1.14.0
- **Redis Sessions**: Working on unicorn-lago-redis
- **Public Pages**: Plans, signup, and billing settings pages live
- **Docker Network**: All containers connected and communicating

### 📍 Key URLs

| Service | URL |
|---------|-----|
| **Plans Page** | https://unicorncommander.ai/plans.html |
| **Signup Flow** | https://unicorncommander.ai/signup-flow.html |
| **Billing Settings** | https://unicorncommander.ai/billing-settings.html |
| **Plans API** | https://unicorncommander.ai/api/v1/subscriptions/plans |
| **Lago Admin** | https://billing.unicorncommander.ai |

### 💰 Subscription Plans

```
Trial:        $1/month   (7-day trial, 700 total API calls)
Starter:      $19/month  (1,000 calls/month, BYOK enabled)
Professional: $49/month  (10,000 calls/month, TTS/STT, LiteLLM)
Enterprise:   $99/month  (Unlimited calls, team management)
```

### 🔑 Environment Variables (Configured)

**Stripe** (Test Mode):
- ✅ `STRIPE_PUBLISHABLE_KEY`
- ✅ `STRIPE_SECRET_KEY`
- ✅ `STRIPE_API_KEY`
- ⏳ `STRIPE_WEBHOOK_SECRET` (needs webhook setup)

**Lago**:
- ✅ `LAGO_API_URL=http://unicorn-lago-api:3000`
- ✅ `LAGO_PUBLIC_URL=https://billing-api.unicorncommander.ai`
- ⏳ `LAGO_API_KEY` (will be set by webhook agent)

**Redis**:
- ✅ `REDIS_URL=redis://unicorn-lago-redis:6379/0`

---

## 🎯 Next Steps (In Order)

### 1. Create Stripe Products ⏳
```bash
docker exec ops-center-direct python /app/backend/setup_stripe_products.py
```
This creates 4 products and 8 prices in your Stripe account.

### 2. Configure Stripe Webhook ⏳
1. Go to: https://dashboard.stripe.com/test/webhooks
2. Add endpoint: `https://unicorncommander.ai/api/v1/billing/webhooks/stripe`
3. Select events:
   - `checkout.session.completed`
   - `customer.subscription.*`
   - `invoice.paid`
   - `invoice.payment_failed`
4. Copy webhook secret to `.env.auth`
5. Restart: `docker restart ops-center-direct`

### 3. Initialize Lago (Automated by webhook agent) ⏳
The webhook agent will:
- Get Lago API key
- Update ops-center environment
- Configure Lago billable metrics
- Set up usage aggregations

### 4. Test Payment Flow 🧪
```bash
# Test with Stripe test card: 4242 4242 4242 4242
1. Visit: https://unicorncommander.ai/plans.html
2. Click "Subscribe" on any plan
3. Complete checkout
4. Verify subscription in Keycloak user attributes
5. Check Lago for usage tracking
```

---

## 🔍 Verification Commands

### Check Ops Center Status
```bash
docker logs ops-center-direct --tail 30
```
Should show:
```
✅ INFO: Stripe payment API endpoints registered at /api/v1/billing
✅ INFO: Lago webhooks registered at /api/v1/webhooks/lago
```

### Test API Endpoints
```bash
# Subscription plans
curl https://unicorncommander.ai/api/v1/subscriptions/plans | jq

# Health check (should return 401 - auth required)
curl https://unicorncommander.ai/api/v1/billing/subscription-status
```

### Check Lago Connectivity
```bash
docker exec ops-center-direct curl http://unicorn-lago-api:3000/health
```
Should return:
```json
{"version":"v1.14.0","message":"Success"}
```

### Verify Stripe Configuration
```bash
docker exec ops-center-direct env | grep STRIPE
```

---

## 📋 Integration Files

| File | Purpose |
|------|---------|
| `stripe_integration.py` | Core Stripe logic (customer creation, subscriptions) |
| `stripe_api.py` | FastAPI endpoints for payments |
| `lago_webhooks.py` | Lago webhook handler |
| `billing_manager.py` | Billing coordination layer |
| `subscription_manager.py` | Subscription plans and tier management |

---

## 🐛 Common Issues

### "Not authenticated" on billing endpoints
✅ **Expected behavior** - All `/api/v1/billing/*` endpoints require authentication

### "Lago API key not set"
⏳ **Normal** - Will be set automatically by webhook agent after Lago initialization

### Plans page returns 404
❌ Check Traefik routing and ensure ops-center-direct is running:
```bash
docker ps | grep ops-center
docker logs ops-center-direct
```

### Stripe webhook fails
❌ Check webhook secret is set correctly:
```bash
docker exec ops-center-direct env | grep STRIPE_WEBHOOK_SECRET
```

---

## 📞 Support

**Logs**:
```bash
# Ops Center
docker logs ops-center-direct -f

# Lago API
docker logs unicorn-lago-api -f

# Lago Worker
docker logs unicorn-lago-worker -f
```

**Configuration Files**:
- Environment: `/home/muut/Production/UC-1-Pro/services/ops-center/.env.auth`
- Docker Compose: `/home/muut/Production/UC-1-Pro/services/ops-center/docker-compose.direct.yml`
- Full Status: `/home/muut/Production/UC-1-Pro/services/ops-center/OPS_CENTER_BILLING_INTEGRATION_STATUS.md`

---

**Last Updated**: October 11, 2025
**Status**: Ready for Stripe product setup and webhook configuration
