# Epic 2.4: Self-Service Upgrades - Testing Checklist

**Date**: October 24, 2025
**Status**: ⏳ AWAITING MANUAL TESTING
**Priority**: P1 - Test before announcing to users

---

## 🧪 Manual Testing Required

### Test 1: Upgrade Flow (Trial → Professional)

**Prerequisites**:
- Login with trial tier user
- Have Stripe test mode enabled
- Use test card: 4242 4242 4242 4242

**Steps**:
1. ✅ Navigate to https://unicorncommander.ai/admin/upgrade
2. ✅ Verify TierComparison component loads with 4 tiers
3. ✅ Verify "Trial" tier shows as current (green badge)
4. ✅ Click "Upgrade to Professional" button
5. ✅ Verify UpgradeFlow wizard opens (Step 1 of 3)
6. ✅ Click "Continue" to proceed to Step 2
7. ✅ Verify proration preview shows:
   - Old tier: Trial ($1/week)
   - New tier: Professional ($49/month)
   - Proration amount (should be ~$49)
8. ✅ Click "Proceed to Payment"
9. ✅ Verify redirected to Stripe Checkout
10. ✅ Enter test card: 4242 4242 4242 4242, Exp: 12/34, CVC: 123
11. ✅ Complete payment
12. ✅ Verify redirected back to ops-center with success message
13. ✅ Check user's tier updated to "Professional" in UI
14. ✅ Check email received (upgrade confirmation)
15. ✅ Check Keycloak: `subscription_tier` attribute = "professional"
16. ✅ Check database: `subscription_changes` table has record

**Expected Results**:
- Upgrade completes in < 2 minutes
- No errors in browser console
- Tier updates immediately after payment
- Confirmation email received within 1 minute

**Test Card Details**:
```
Card: 4242 4242 4242 4242
Expiry: Any future date (e.g., 12/34)
CVC: Any 3 digits (e.g., 123)
ZIP: Any 5 digits (e.g., 12345)
```

---

### Test 2: Downgrade Flow (Professional → Starter)

**Prerequisites**:
- Login with professional tier user
- User has active subscription

**Steps**:
1. ✅ Navigate to https://unicorncommander.ai/admin/plans
2. ✅ Verify TierComparison shows "Professional" as current
3. ✅ Click "Downgrade to Starter" button
4. ✅ Verify warning dialog appears with:
   - Feature loss warning
   - "You'll keep Pro until [end of period date]"
   - "Confirm Downgrade" button
5. ✅ Click "Confirm Downgrade"
6. ✅ Verify success message: "Downgrade scheduled for [date]"
7. ✅ Verify effective_date is end of current billing period
8. ✅ Check email received (downgrade confirmation)
9. ✅ Check database: `subscription_changes` table has record with:
   - change_type: "downgrade"
   - effective_date: [end of period]
   - old_tier: "professional"
   - new_tier: "starter"
10. ✅ Verify user still has Pro access until effective date

**Expected Results**:
- Downgrade scheduled, not immediate
- User keeps Pro features until end of billing period
- Confirmation email received
- Database record created

---

### Test 3: Proration Calculation (Mid-Month Upgrade)

**Prerequisites**:
- User on Starter plan ($19/month)
- Current date is mid-month (e.g., 15th of month)
- User subscribed on 1st of month

**Steps**:
1. ✅ Navigate to `/admin/upgrade`
2. ✅ Select "Professional" tier ($49/month)
3. ✅ View proration preview on Step 2
4. ✅ Verify calculation shows:
   ```
   Days remaining in period: ~15 days
   Daily rate (Professional): $49 / 30 = $1.63/day
   Days paid for (Starter): ~15 days at $0.63/day = $9.50
   Proration amount: ($1.63 - $0.63) × 15 = $15.00
   Total due today: ~$15.00
   ```
5. ✅ Complete upgrade with Stripe
6. ✅ Verify Stripe invoice shows same proration amount
7. ✅ Check `subscription_changes.proration_amount` matches

**Expected Results**:
- Proration calculation is accurate (within $0.50)
- Stripe invoice matches preview
- Database stores correct amount

---

### Test 4: Webhook Processing (Stripe → Ops-Center)

**Prerequisites**:
- Stripe webhook configured in Stripe dashboard
- Webhook URL: https://unicorncommander.ai/api/v1/webhooks/stripe/checkout-completed
- Webhook secret configured in `.env.auth`

**Steps**:
1. ✅ Complete an upgrade via Stripe Checkout
2. ✅ Check Stripe dashboard → Webhooks → Recent deliveries
3. ✅ Verify `checkout.session.completed` event sent
4. ✅ Verify webhook response: 200 OK
5. ✅ Check ops-center logs:
   ```bash
   docker logs ops-center-direct | grep -i webhook
   ```
6. ✅ Verify logs show:
   - "Received Stripe webhook: checkout.session.completed"
   - "Verified webhook signature"
   - "Updated subscription in Lago"
   - "Updated user tier in Keycloak"
   - "Sent confirmation email"
7. ✅ Check database: `subscription_changes` has `stripe_session_id`
8. ✅ Verify no errors in logs

**Expected Results**:
- Webhook receives within 5 seconds of payment
- Signature verification passes
- All actions complete successfully
- No errors or warnings

---

### Test 5: Edge Cases & Error Handling

#### 5a. Declined Card
**Steps**:
1. ✅ Start upgrade flow
2. ✅ Use declined test card: 4000 0000 0000 0002
3. ✅ Complete checkout form
4. ✅ Verify Stripe shows "Your card was declined"
5. ✅ Verify user NOT upgraded (tier unchanged)
6. ✅ Verify `subscription_changes` has no record
7. ✅ Verify user can retry payment

**Expected**: Payment declined gracefully, no tier change

#### 5b. Upgrade to Same Tier
**Steps**:
1. ✅ Login as Starter user
2. ✅ Try to upgrade to Starter again
3. ✅ Verify API returns 400 error: "Already on this tier"
4. ✅ Verify UI shows error message

**Expected**: Error message, no API call made

#### 5c. Insufficient Funds
**Steps**:
1. ✅ Use test card: 4000 0000 0000 9995
2. ✅ Attempt upgrade
3. ✅ Verify Stripe shows "Insufficient funds"
4. ✅ Verify graceful error handling

**Expected**: Payment failed, user can retry

#### 5d. Network Timeout
**Steps**:
1. ✅ Start upgrade flow
2. ✅ Disconnect internet before completing payment
3. ✅ Verify timeout error shown
4. ✅ Reconnect and retry
5. ✅ Verify retry works

**Expected**: Timeout handled, retry successful

---

### Test 6: UI/UX Validation

#### 6a. Responsive Design
**Devices to Test**:
- ✅ Mobile (320px width) - iPhone SE
- ✅ Tablet (768px width) - iPad
- ✅ Desktop (1920px width) - Large monitor

**Checks**:
- ✅ Tier cards stack properly on mobile (1 column)
- ✅ Tier cards show 2 columns on tablet
- ✅ Tier cards show 4 columns on desktop
- ✅ All text readable
- ✅ Buttons accessible (44x44px min touch target)
- ✅ No horizontal scrolling

#### 6b. Accessibility (WCAG AA)
**Checks**:
- ✅ All buttons have aria-labels
- ✅ Color contrast meets WCAG AA (4.5:1 for text)
- ✅ Keyboard navigation works (Tab, Enter, Esc)
- ✅ Screen reader announces tier names and prices
- ✅ Focus indicators visible
- ✅ Form labels associated with inputs

**Tools**:
- Chrome DevTools → Lighthouse → Accessibility
- WAVE browser extension
- Keyboard-only navigation test

#### 6c. Performance
**Checks**:
- ✅ Page load < 2 seconds
- ✅ API response < 500ms
- ✅ Stripe redirect < 1 second
- ✅ No layout shift (CLS < 0.1)
- ✅ Animations smooth (60fps)

**Tools**:
- Chrome DevTools → Performance
- Network tab for API timing
- Lighthouse performance score

---

### Test 7: Cross-Browser Compatibility

**Browsers to Test**:
- ✅ Chrome/Edge (latest)
- ✅ Firefox (latest)
- ✅ Safari (latest)
- ✅ Mobile Safari (iOS)
- ✅ Chrome Mobile (Android)

**Checks**:
- ✅ UI renders correctly
- ✅ Animations work
- ✅ Stripe Checkout opens
- ✅ Payment completes
- ✅ No console errors

---

### Test 8: Email Notifications

#### 8a. Upgrade Confirmation Email
**Trigger**: Complete upgrade
**Checks**:
- ✅ Email received within 1 minute
- ✅ Subject: "Subscription Upgraded to Professional"
- ✅ Body includes:
  - Old tier name
  - New tier name
  - Features unlocked
  - Effective date (immediate)
  - Invoice link
- ✅ HTML and plain text versions
- ✅ Unsubscribe link present
- ✅ Formatting correct in Gmail, Outlook, Apple Mail

#### 8b. Downgrade Confirmation Email
**Trigger**: Schedule downgrade
**Checks**:
- ✅ Email received within 1 minute
- ✅ Subject: "Subscription Downgrade Scheduled"
- ✅ Body includes:
  - Current tier name
  - New tier name (effective [date])
  - Features you'll lose
  - How to cancel downgrade
- ✅ HTML and plain text versions

---

## 🤖 Automated Testing

### Backend Tests (pytest)
```bash
cd /home/muut/Production/UC-Cloud/services/ops-center/backend
pytest tests/test_subscription_upgrade.py -v --cov=subscription_api
```

**Expected**:
- ✅ 65 tests pass
- ✅ 80%+ coverage
- ✅ All assertions succeed

### Frontend Tests (Jest/Vitest)
```bash
cd /home/muut/Production/UC-Cloud/services/ops-center
npm test -- TierComparison.test.jsx
```

**Expected**:
- ✅ 48 tests pass
- ✅ All components render
- ✅ User interactions work

### E2E Tests (pytest)
```bash
cd /home/muut/Production/UC-Cloud/services/ops-center/backend
pytest tests/e2e/test_upgrade_flow.py -v
```

**Expected**:
- ✅ 45 tests pass
- ✅ Full upgrade/downgrade flows succeed
- ✅ Webhook handling verified

---

## 📊 Testing Summary

### Completion Checklist

- [ ] **Test 1**: Upgrade flow (Trial → Professional)
- [ ] **Test 2**: Downgrade flow (Professional → Starter)
- [ ] **Test 3**: Proration calculation (mid-month)
- [ ] **Test 4**: Webhook processing
- [ ] **Test 5**: Edge cases (5 scenarios)
- [ ] **Test 6**: UI/UX validation (responsive, a11y, perf)
- [ ] **Test 7**: Cross-browser (5 browsers)
- [ ] **Test 8**: Email notifications (2 types)
- [ ] **Automated**: Backend tests (65 tests)
- [ ] **Automated**: Frontend tests (48 tests)
- [ ] **Automated**: E2E tests (45 tests)

### Estimated Testing Time

| Category | Time |
|----------|------|
| Manual testing (Tests 1-8) | 1-2 hours |
| Automated testing | 15 minutes |
| Bug fixes (if any) | 0-2 hours |
| **Total** | **2-4 hours** |

---

## 🐛 Known Issues to Monitor

Based on Testing & UX Lead's analysis:

1. **Proration Edge Case** (P2): Calculation may be off by $0.01 for mid-month upgrades due to float rounding
   - **Workaround**: Use `Decimal` type for currency
   - **Fix**: Update `lago_integration.py` line 145

2. **Payment Failure Retry** (P1): Retry button doesn't re-initialize Stripe checkout
   - **Impact**: Users must refresh page to retry
   - **Fix**: Call `create_checkout_session()` again on retry

3. **Keycloak Attribute Delay** (P2): User attribute updates may take 1-2 seconds to sync
   - **Impact**: UI may show old tier for brief moment
   - **Workaround**: Poll for update or show loading state

---

## ✅ Sign-Off

Once all tests pass:

- [ ] **QA Lead**: Signs off on manual testing
- [ ] **Developer**: Confirms automated tests pass
- [ ] **Product Manager**: Approves for production announcement
- [ ] **User Documentation**: Updated with upgrade instructions
- [ ] **Support Team**: Briefed on new feature

---

## 📞 Support Contacts

**If issues found**:
- **P0 (Critical)**: Stop testing, report immediately
- **P1 (High)**: Document and report after test completion
- **P2 (Medium)**: Add to backlog for next sprint
- **P3 (Low)**: Nice-to-have improvements

**Report to**:
- GitHub Issues: https://github.com/Unicorn-Commander/UC-Cloud/issues
- Label: `epic-2.4`, `testing`, `priority-[P0-P3]`

---

**Testing Owner**: QA Team
**Target Completion**: Within 24 hours of deployment
**Status**: ⏳ PENDING
