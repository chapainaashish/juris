# Testing Subscription API Endpoints: Step-by-Step Instructions

## Prerequisites

* Install a tool like Postman or use curl for API testing
* Run the application using docker

## Important Notes About the System

1. **Automatic Trial Subscription**: A 15-day trial subscription is automatically created when a vendor completes their profile. No manual trial creation is needed.

2. **Subscription Cancellation Behavior**: When cancelling a subscription, it remains active until the end of the current subscription plan period. This is because the user has already paid for this period. The status changes to "canceled" but the subscription remains functional until its expiration date.

3. **Stripe Webhooks in Production**: The Stripe CLI is only for local development. In production, Stripe will directly send webhook events to our server, so we need to remove the stripe/cli image in production.

## Step 1: User and Profile Registration

1. Create user with Sign up endpoint:
   ```
   POST /api/user/signup/
   {
     "email": "test@example.com",
     "password": "securepassword123"
   }
   ```

2. Verify the email (from admin panel)

3. Login the user and get JWT access token:
   ```
   POST /api/user/login/
   {
     "email": "test@example.com",
     "password": "securepassword123"
   }
   ```

4. Complete the Profile from various profile endpoints

5. Upon completion of profile:
   * New subscription will be created automatically
   * New Stripe customer will be added in the stripe dashboard
   * Subscription invoice will be generated in the subscription model with stripe pdf
   * Note the bill amount will be 0 since it's a free trial and user haven't paid yet

## Step 2: Set Up WebSocket for Notifications

1. Generate the token for websocket:
   ```
   GET /api/user/ws
   ```
   Response:
   ```json
   {
     "uuid": "a33b02ca-df44-4ddb-a042-c3928badbf8e"
   }
   ```

2. Connect to the websocket using:
   ```
   ws://localhost:8000/ws/notifications/?uuid=a33b02ca-df44-4ddb-a042-c3928badbf8e
   ```

3. You will receive notifications via WebSocket for these event types:
   ```
   "trial_ending" - Trial Ending
   "free_period_ending" - Free Period Ending
   "subscription_renewing" - Subscription Renewing
   "payment_failed" - Payment Failed
   "subscription_canceled" - Subscription Canceled
   "subscription_activated" - Subscription Activated
   "general" - General Notification
   ```

4. Example of a notification you'll receive:
   ```json
   {
     "type": "notification",
     "notification": {
       "id": 7,
       "type": "subscription_activated",
       "message": "Your subscription has been activated successfully.",
       "read": false,
       "created_at": "2025-04-27T15:30:45Z"
     }
   }
   ```

5. To mark a notification as read, send this message to the WebSocket:
   ```json
   {
     "type": "mark_read",
     "notification_id": 7
   }
   ```

6. For time-sensitive notifications (trial ending, renewal, etc.), the system uses Stripe webhooks to send notifications 2 days before the event. The webhook.py handler processes these events and sends both email messages and in-app notifications.

## Step 3: Check Trial Subscription Status

1. Get the subscription details:
   ```
   GET /api/subscription/
   ```

2. Verify the response shows a trial subscription with status "trialing"

## Step 4: Test Voucher Validation

1. Validate a voucher code:
   ```
   POST /api/subscription/vouchers/validate
   {
     "code": "WELCOME30"
   }
   ```

2. Verify the response shows if the voucher is valid or not

## Step 5: Activate Subscription with Payment Method

1. To set up payment, request a client secret:
   ```
   POST /api/subscription/payment-methods/
   ```

2. The backend will return the client secret which should be used in frontend to get the user card details

3. Use Stripe's test card in your frontend implementation:
   - Test card number: 4242 4242 4242 4242
   - Expiration: Any future date
   - CVC: Any 3 digits
   - ZIP: Any 5 digits

4. After successful frontend setup, you'll receive a payment method ID

5. Activate the subscription:
   ```
   PUT /api/subscription/activate
   {
     "payment_method_id": "pm_xxx", 
     "voucher_code": "WELCOME30"  // Optional
   }
   ```

6. Verify the subscription status changed to "active"
7. You'll receive a WebSocket notification about the activation

## Step 6: Check Payment Methods

1. List payment methods:
   ```
   GET /api/subscription/payment-methods/
   ```

2. Verify your card appears in the list

## Step 7: Test Notifications

1. List notifications:
   ```
   GET /api/subscription/notifications/
   ```

2. Verify you received a subscription activation notification

## Step 8: Check Invoices

1. List invoices:
   ```
   GET /api/subscription/invoices
   ```

## Step 9: Test Subscription Cancellation

1. Cancel the subscription:
   ```
   PUT /api/subscription/cancel
   {
     "cancel_at_period_end": true
   }
   ```

2. Verify the subscription status changed to "canceled" but remains active until the end of the current period
3. You'll receive a WebSocket notification about the cancellation
4. Note: If you cancel the subscription from the API, you don't need to go to stripe to cancel it - our application will automatically cancel it from stripe too.

