# Auth Testing Playbook — Anjali Herbal Life Ayurveda

Auth uses JWT Bearer tokens (returned in response body, stored in localStorage on frontend).

## Admin
- Email: sachin.shukla2196@gmail.com
- Password: Admin@12345
- Role: super_admin

## API tests
```
API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d '=' -f2)
# login
curl -s -X POST "$API/api/auth/login" -H "Content-Type: application/json" \
  -d '{"email":"sachin.shukla2196@gmail.com","password":"Admin@12345"}'
# me
TOKEN=... ; curl -s "$API/api/auth/me" -H "Authorization: Bearer $TOKEN"
```

## Registration (OTP mocked, returned as dev_otp)
```
curl -s -X POST "$API/api/auth/send-otp" -H "Content-Type: application/json" \
  -d '{"email":"userA@test.com","mobile":"9876543210"}'
# use dev_otp in register
curl -s -X POST "$API/api/auth/register" -H "Content-Type: application/json" \
  -d '{"full_name":"User A","email":"userA@test.com","mobile":"9876543210","password":"Pass@123","confirm_password":"Pass@123","otp":"<dev_otp>","accept_terms":true}'
```

## Activation & commission
- Create order with ANJ-STARTER product, checkout, then GET /api/payments/status/{session_id}.
- In preview, payment auto-verifies via Stripe status polling once the checkout is completed with test card 4242 4242 4242 4242.
