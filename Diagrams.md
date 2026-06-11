# Juris - System Diagrams

All diagrams are written in [Mermaid](https://mermaid.js.org/)

## 1. Sequence Diagram - Appointment Lifecycle

Full flow from registration through booking, payment, video consultation, and fund release. Cancellation/refund path shown as an alternate.

```mermaid
sequenceDiagram
    actor Client
    participant API as Juris API (Django/DRF)
    participant DB as PostgreSQL
    participant Redis
    participant Celery
    participant Stripe
    participant Agora as Agora RTC
    participant Twilio
    participant SendGrid
    actor Lawyer

    %% ── AUTHENTICATION ──────────────────────────────────
    Note over Client,Twilio: Registration & Login
    Client->>API: POST /auth/register/
    API->>DB: Create User (is_email_verified=false)
    API->>SendGrid: Send verification email
    Client->>API: GET /auth/verify-email/?token=...
    API->>DB: User.is_email_verified = true

    Client->>API: POST /auth/login/ {email, password}
    API->>DB: Validate credentials
    API->>Twilio: Send OTP SMS
    Client->>API: POST /auth/verify-otp/ {token, otp}
    API-->>Client: {access_token, refresh_token}

    %% ── VENDOR ONBOARDING (Lawyer) ───────────────────────
    Note over Lawyer,DB: Lawyer Profile Setup (9-step flow)
    Lawyer->>API: POST /auth/register/ + login (same flow)
    Lawyer->>API: POST /profiles/complete/category/ {token, category}
    Lawyer->>API: POST /profiles/complete/business-name/ {token, name}
    Lawyer->>API: POST /profiles/complete/address/ {token, address}
    Lawyer->>API: POST /profiles/complete/legal-info/ {token, ...}
    Lawyer->>API: POST /profiles/complete/complete/ {token}
    API->>DB: VendorProfile.is_completed = true
    API->>DB: Create LawyerProfile + Wallet

    %% ── DISCOVERY ──────────────────────────────────────
    Note over Client,DB: Browsing & Calendar
    Client->>API: GET /lawyers/?category=&vendor_type=lawyer
    API->>DB: SELECT LawyerProfile + VendorProfile (N+1-safe select_related)
    API-->>Client: Paginated lawyer listings with pricing

    Client->>API: GET /availability/calendar/?lawyer_id=&start_date=&end_date=
    API->>DB: Fetch Availability (weekly schedule)
    API->>DB: Fetch Unavailability (blocked dates / all-day)
    API-->>Client: Available time slots per day (up to 90-day range)

    Client->>API: GET /availability/check-time/?lawyer_id=&start=&end=
    API-->>Client: {available: true/false}

    %% ── BOOKING & PAYMENT ───────────────────────────────
    Note over Client,Stripe: Booking & Escrow Payment
    Client->>API: POST /lawyer/appointment/ {offering_type_id, start_datetime, notes}
    API->>DB: Validate slot (no overlap check)
    API->>DB: Create Appointment (status=PENDING)
    API->>DB: Create Transaction (type=PAYMENT, status=PENDING)
    API->>Stripe: Create PaymentIntent (amount_cents, currency=usd)
    Stripe-->>API: {payment_intent_id, client_secret}
    API->>DB: Save stripe_payment_intent_id on Appointment
    API->>Celery: Schedule auto-cancel task (10 min payment timeout)
    API->>Redis: Persist task ID
    API-->>Client: {appointment_id, client_secret}

    Client->>Stripe: Confirm payment (card details + client_secret)
    Stripe->>API: POST /stripe/webhook/ — payment_intent.succeeded
    API->>DB: Appointment.status → CONFIRMED
    API->>DB: Transaction stripe_id recorded
    API->>Celery: Revoke auto-cancel task
    API->>Celery: Schedule 24-hr reminder task
    Celery-->>Lawyer: Push notification + email (appointment tomorrow)

    %% ── CONSULTATION ─────────────────────────────────────
    Note over Client,Lawyer: Day of Appointment
    alt Video or Audio consultation
        Client->>API: GET /appointment/{id}/session/token/
        API->>Agora: Generate RTC token (channel, uid=client, role=Subscriber)
        Agora-->>API: Agora token
        API-->>Client: {agora_token, channel_name}

        Lawyer->>API: GET /appointment/{id}/session/token/
        API->>Agora: Generate RTC token (uid=lawyer, role=Publisher)
        Agora-->>API: Agora token
        API-->>Lawyer: {agora_token, channel_name}

        Client-->>Lawyer: Live video/audio via Agora RTC channel
    else Physical appointment
        Note over Client,Lawyer: Client attends lawyer office in person
    end

    %% ── COMPLETION & FUND RELEASE ────────────────────────
    Note over Client,DB: Completion & Fund Release (atomic)
    Client->>API: POST /appointment/{id}/complete/
    API->>DB: Assert end_datetime <= now()
    API->>DB: BEGIN TRANSACTION
    API->>DB: Appointment.status → COMPLETED
    API->>DB: Transaction.status → COMPLETED
    API->>DB: SELECT FOR UPDATE Wallet (lawyer)
    API->>DB: wallet.balance += lawyer_amount
    API->>DB: COMMIT
    API-->>Client: {message: "Appointment completed, funds released"}
    API-->>Lawyer: In-app notification — earnings credited

    %% ── WITHDRAWAL ───────────────────────────────────────
    Note over Lawyer,Stripe: Optional — Withdrawal
    Lawyer->>API: POST /wallet/withdraw/ {amount}
    API->>DB: BEGIN TRANSACTION + SELECT FOR UPDATE Wallet
    API->>DB: Assert balance >= amount, wallet not locked
    API->>Stripe: Create Payout to bank account
    Stripe-->>API: Payout created
    API->>DB: Create Transaction (type=PAYOUT, status=COMPLETED)
    API->>DB: wallet.balance -= amount
    API->>DB: COMMIT

    %% ── CANCELLATION PATH ─────────────────────────────────
    Note over Client,Stripe: Alternate Path — Cancellation & Refund
    Client->>API: POST /appointment/{id}/cancel/ {reason}
    API->>DB: Appointment.status → CANCELLED
    API->>Stripe: Create Refund (payment_intent_id)
    Stripe-->>API: Refund object created
    API->>DB: refund_status → APPROVED
    Stripe->>API: POST /stripe/webhook/ — charge.refund.succeeded
    API->>DB: Transaction.status → COMPLETED (refund)
    API-->>Client: Notification — refund confirmed
    API-->>Lawyer: Notification — appointment cancelled
```

## 2. Data Flow Diagram (DFD)

Level-1 DFD showing data flows between external entities, system processes, and data stores.

```mermaid
flowchart TD
    %% ── External Entities ───────────────────────────────
    CLIENT["[E] Client"]
    LAWYER["[E] Lawyer / Vendor"]
    STRIPE["[E] Stripe"]
    TWILIO["[E] Twilio SMS"]
    SENDGRID["[E] SendGrid Email"]
    AGORA["[E] Agora RTC"]
    CLOUDINARY["[E] Cloudinary CDN"]

    %% ── Processes ────────────────────────────────────────
    P1(["1.0 · User Auth\n& 2FA"])
    P2(["2.0 · Vendor\nOnboarding"])
    P3(["3.0 · Availability\n& Calendar"])
    P4(["4.0 · Appointment\nBooking"])
    P5(["5.0 · Payment\nProcessing"])
    P6(["6.0 · Subscription\nManagement"])
    P7(["7.0 · Wallet &\nWithdrawals"])
    P8(["8.0 · KYC\nVerification"])
    P9(["9.0 · Notification\nService"])
    P10(["10.0 · Real-time\nConsultation"])

    %% ── Data Stores ──────────────────────────────────────
    DS1[("Users &\nTokens")]
    DS2[("Profiles, Legal\nInfo & KYC")]
    DS3[("Appointments\n& Sessions")]
    DS4[("Transactions\n& Wallets")]
    DS5[("Subscriptions\n& Vouchers")]
    DS6[("Availability &\nUnavailability")]

    %% ── External → Process ───────────────────────────────
    CLIENT -->|"credentials / OTP"| P1
    LAWYER -->|"credentials / OTP"| P1
    CLIENT -->|"profile search, date range"| P3
    LAWYER -->|"schedule, unavailability"| P3
    CLIENT -->|"offering type, time slot"| P4
    LAWYER -->|"profile data, avatar"| P2
    LAWYER -->|"subscription choice, voucher"| P6
    LAWYER -->|"withdrawal amount"| P7
    LAWYER -->|"identity documents"| P8
    CLIENT -->|"Agora join"| P10
    LAWYER -->|"Agora join"| P10

    %% ── Process → External ───────────────────────────────
    P1 -->|"JWT access + refresh"| CLIENT
    P1 -->|"JWT access + refresh"| LAWYER
    P1 -->|"OTP request"| TWILIO
    P1 -->|"verification email"| SENDGRID
    P3 -->|"available slots + pricing"| CLIENT
    P5 -->|"PaymentIntent creation"| STRIPE
    P6 -->|"Stripe subscription"| STRIPE
    P7 -->|"payout request"| STRIPE
    P8 -->|"identity session"| STRIPE
    P9 -->|"WebSocket push"| CLIENT
    P9 -->|"WebSocket push"| LAWYER
    P9 -->|"transactional email"| SENDGRID
    P10 -->|"RTC token + channel"| CLIENT
    P10 -->|"RTC token + channel"| LAWYER
    P2 -->|"avatar / media upload"| CLOUDINARY

    %% ── External → Process (inbound webhooks) ────────────
    STRIPE -->|"payment / refund / dispute webhooks"| P5
    STRIPE -->|"billing / subscription webhooks"| P6
    STRIPE -->|"KYC result webhook"| P8
    TWILIO -->|"OTP delivery status"| P1
    AGORA -->|"RTC token"| P10
    CLOUDINARY -->|"media URL"| P2

    %% ── Process ↔ Data Store ─────────────────────────────
    P1 <-->|"read / write users"| DS1
    P2 <-->|"read / write profiles"| DS2
    P3 <-->|"read / write schedule"| DS6
    P4 <-->|"create / update appointments"| DS3
    P5 <-->|"create / update transactions"| DS4
    P6 <-->|"read / write subscriptions"| DS5
    P7 <-->|"read / update wallet + tx"| DS4
    P8 -->|"update KYC status"| DS2
    P9 <-->|"read / write notifications"| DS1
    P10 <-->|"read / write sessions"| DS3

    %% ── Cross-process ────────────────────────────────────
    P4 -->|"trigger payment"| P5
    P4 -->|"emit booking event"| P9
    P5 -->|"release funds"| P7
    P5 -->|"emit payment event"| P9
    P6 -->|"emit billing event"| P9
    P7 -->|"emit payout event"| P9
```

## 3. Use Case Diagram

Actors and their system capabilities across all platform features.

```mermaid
flowchart LR
    %% ── Actors ───────────────────────────────────────────
    C(["👤\nClient"])
    L(["👤\nLawyer / Vendor"])
    A(["👤\nAdmin"])
    ST(["⚙️\nStripe"])
    TW(["⚙️\nTwilio"])

    subgraph SYS ["⬜  Juris Platform"]
        direction TB

        subgraph AUTH ["Authentication & Account"]
            R1["Register & Verify Email"]
            R2["Login with 2FA (SMS OTP)"]
            R3["Sign In with Google OAuth2"]
            R4["Enable / Disable 2FA"]
            R5["Reset Password via Email"]
            R6["Check Email Availability"]
        end

        subgraph CLIENT_UC ["Client Features"]
            CU1["Browse & Search Lawyers"]
            CU2["Filter by Category / Type"]
            CU3["View Lawyer Profile & Pricing"]
            CU4["View Availability Calendar"]
            CU5["Check Specific Time Slot"]
            CU6["Book Appointment"]
            CU7["Pay via Stripe"]
            CU8["Join Video / Audio Call (Agora)"]
            CU9["Mark Appointment Complete"]
            CU10["Cancel Appointment & Refund"]
            CU11["Reschedule Appointment"]
            CU12["View Appointment History"]
        end

        subgraph VENDOR_UC ["Lawyer / Vendor Features"]
            VU1["Complete 9-Step Vendor Profile"]
            VU2["Set Offerings & Pricing Plans"]
            VU3["Add Physical / Audio / Video Types"]
            VU4["Set Weekly Availability Schedule"]
            VU5["Block Unavailability Dates"]
            VU6["Bulk Create / Copy Availability"]
            VU7["Conduct Video / Audio Consultation"]
            VU8["View Wallet Balance & History"]
            VU9["Request Payout / Withdrawal"]
            VU10["Subscribe to Platform Plan"]
            VU11["Apply Voucher Discount Code"]
            VU12["Save Payment Method (Card)"]
            VU13["Complete KYC Identity Verification"]
        end

        subgraph ADMIN_UC ["Admin / Platform"]
            AU1["Approve Withdrawal Requests"]
            AU2["Manage Subscription Plans"]
            AU3["Handle Stripe Charge Disputes"]
            AU4["Monitor KYC Verifications"]
            AU5["Manage Voucher Codes"]
        end
    end

    %% ── Actor connections ─────────────────────────────────
    C --- R1 & R2 & R3 & R4 & R5 & R6
    C --- CU1 & CU2 & CU3 & CU4 & CU5
    C --- CU6 & CU7 & CU8 & CU9 & CU10 & CU11 & CU12

    L --- R1 & R2 & R3 & R4 & R5
    L --- VU1 & VU2 & VU3 & VU4 & VU5 & VU6
    L --- VU7 & VU8 & VU9 & VU10 & VU11 & VU12 & VU13

    A --- AU1 & AU2 & AU3 & AU4 & AU5

    ST --- CU7 & CU10 & VU9 & VU10 & VU13 & AU3
    TW --- R2 & R4
```

## 4. Entity Relationship Diagram (ER)

Full data model covering all major Django apps: `users`, `profiles`, `lawyer`, `lawyer_availability`, `lawyer_appointment`, `lawyer_wallet`, `subscriptions`, `kyc`.

```mermaid
erDiagram

    %% ── USERS ────────────────────────────────────────────
    USER {
        uuid    id                         PK
        string  email                      UK
        string  phone_number               UK
        string  role
        string  vendor_type
        boolean is_email_verified
        boolean is_2fa_enabled
        boolean has_initiate_login
        int     password_attempt
        datetime created_at
    }

    PASSWORD_RESET_TOKEN {
        int     id         PK
        int     user_id    FK
        string  token      UK
        datetime expires_at
        boolean is_used
    }

    PROFILE_COMPLETION_SESSION {
        uuid    id         PK
        int     user_id    FK
        string  token      UK
        datetime expires_at
        boolean is_completed
    }

    %% ── PROFILES ─────────────────────────────────────────
    CATEGORY {
        int    id    PK
        string name  UK
    }

    LANGUAGE {
        int    id       PK
        string name     UK
        string icon_url
    }

    ADDRESS {
        int     id        PK
        string  street
        string  city
        string  postcode
        string  country
        decimal latitude
        decimal longitude
    }

    VENDOR_PROFILE {
        uuid    id              PK
        int     user_id         FK
        int     category_id     FK
        int     address_id      FK
        string  business_name
        string  avatar_url
        string  bio
        boolean is_completed
        datetime created_at
    }

    VENDOR_LEGAL_INFO {
        int    id                 PK
        uuid   vendor_profile_id  FK
        string email
        string bar_association
        string first_name
        string last_name
    }

    %% ── LAWYER ───────────────────────────────────────────
    LAWYER_CATEGORY {
        int    id    PK
        string title UK
    }

    LAWYER_SUBCATEGORY {
        int    id                  PK
        int    lawyercategory_id   FK
        string title
    }

    LAWYER_PROFILE {
        uuid    id                       PK
        uuid    vendor_profile_id        FK
        string  registration_number
        string  fiscal_code
        string  kyc_verification_status
        decimal average_rating
        decimal commission_percentage
    }

    LAWYER_OFFERING {
        uuid    id                 PK
        uuid    lawyer_profile_id  FK
        string  name
        decimal price_per_30min
        boolean is_active
    }

    OFFERING_TYPE {
        uuid   id          PK
        uuid   offering_id FK
        string type
    }

    %% ── AVAILABILITY ─────────────────────────────────────
    AVAILABILITY {
        uuid    id          PK
        uuid    lawyer_id   FK
        uuid    offering_id FK
        int     day_of_week
        time    start_time
        time    end_time
        boolean is_active
    }

    UNAVAILABILITY {
        uuid    id                  PK
        uuid    lawyer_id           FK
        date    date
        time    start_time
        time    end_time
        boolean is_all_day
        string  unavailability_type
        string  reason
    }

    %% ── APPOINTMENTS ─────────────────────────────────────
    APPOINTMENT {
        uuid     id                        PK
        int      client_id                 FK
        uuid     lawyer_id                 FK
        uuid     offering_type_id          FK
        string   status
        datetime start_datetime
        datetime end_datetime
        decimal  total_price
        decimal  lawyer_amount
        decimal  commission_amount
        string   stripe_payment_intent_id
        string   refund_status
        text     notes
        datetime created_at
    }

    APPOINTMENT_SESSION {
        uuid   id                  PK
        uuid   appointment_id      FK
        string agora_channel_name
        string status
    }

    SESSION_PARTICIPANT {
        uuid   id         PK
        uuid   session_id FK
        int    user_id    FK
        string role
    }

    %% ── WALLET & TRANSACTIONS ────────────────────────────
    WALLET {
        uuid    id        PK
        uuid    lawyer_id FK
        decimal balance
        boolean is_locked
        datetime updated_at
    }

    TRANSACTION {
        uuid    id                   PK
        uuid    wallet_id            FK
        uuid    lawyer_id            FK
        int     client_id            FK
        uuid    appointment_id       FK
        string  transaction_type
        string  status
        decimal amount
        string  stripe_transaction_id
        string  idempotency_key      UK
        datetime created_at
    }

    %% ── SUBSCRIPTIONS ────────────────────────────────────
    SUBSCRIPTION_PLAN {
        int     id                PK
        string  name              UK
        decimal price_monthly
        string  stripe_price_id   UK
    }

    VENDOR_SUBSCRIPTION {
        uuid     id                      PK
        uuid     vendor_id               FK
        int      plan_id                 FK
        int      voucher_id              FK
        string   status
        string   stripe_customer_id
        string   stripe_subscription_id
        datetime trial_ends_at
        datetime current_period_end
    }

    VOUCHER {
        int      id             PK
        string   code           UK
        string   discount_type
        decimal  value
        int      usage_limit
        int      used_count
        datetime expires_at
    }

    VOUCHER_USAGE {
        int  id               PK
        int  voucher_id       FK
        uuid subscription_id  FK
    }

    SUBSCRIPTION_INVOICE {
        uuid     id                  PK
        uuid     subscription_id     FK
        string   stripe_invoice_id   UK
        decimal  amount_paid
        datetime period_start
        datetime period_end
    }

    PAYMENT_METHOD {
        uuid   id                          PK
        uuid   vendor_id                   FK
        string stripe_payment_method_id    UK
        string card_brand
        string last4
        int    exp_month
        int    exp_year
    }

    NOTIFICATION {
        uuid     id         PK
        int      user_id    FK
        string   type
        string   message
        boolean  is_read
        datetime created_at
    }

    %% ── KYC ──────────────────────────────────────────────
    KYC_VERIFICATION {
        uuid   id                              PK
        uuid   lawyer_profile_id              FK
        string stripe_verification_session_id UK
        string status
        datetime created_at
    }

    %% ── Relationships ─────────────────────────────────────

    USER ||--o| VENDOR_PROFILE : "has"
    USER ||--o{ PASSWORD_RESET_TOKEN : "issues"
    USER ||--o{ PROFILE_COMPLETION_SESSION : "owns"
    USER ||--o{ APPOINTMENT : "books (client)"
    USER ||--o{ SESSION_PARTICIPANT : "joins as"
    USER ||--o{ NOTIFICATION : "receives"

    VENDOR_PROFILE }o--|| CATEGORY : "belongs to"
    VENDOR_PROFILE }o--o| ADDRESS : "located at"
    VENDOR_PROFILE }o--o{ LANGUAGE : "speaks"
    VENDOR_PROFILE ||--o| VENDOR_LEGAL_INFO : "has legal info"
    VENDOR_PROFILE ||--o| LAWYER_PROFILE : "extends to"
    VENDOR_PROFILE ||--o| VENDOR_SUBSCRIPTION : "subscribed via"
    VENDOR_PROFILE ||--o{ PAYMENT_METHOD : "saves card"

    LAWYER_PROFILE }o--o{ LAWYER_CATEGORY : "classified under"
    LAWYER_CATEGORY ||--o{ LAWYER_SUBCATEGORY : "has sub-categories"
    LAWYER_PROFILE ||--|{ LAWYER_OFFERING : "offers"
    LAWYER_OFFERING ||--|{ OFFERING_TYPE : "available as"
    LAWYER_PROFILE ||--o{ AVAILABILITY : "available on"
    AVAILABILITY }o--|| LAWYER_OFFERING : "priced by"
    LAWYER_PROFILE ||--o{ UNAVAILABILITY : "blocked on"
    LAWYER_PROFILE ||--o{ APPOINTMENT : "receives"
    LAWYER_PROFILE ||--|| WALLET : "owns"
    LAWYER_PROFILE ||--o{ TRANSACTION : "earns"
    LAWYER_PROFILE ||--o| KYC_VERIFICATION : "verified via"

    OFFERING_TYPE ||--o{ APPOINTMENT : "type for"

    APPOINTMENT ||--o| APPOINTMENT_SESSION : "has session"
    APPOINTMENT ||--o{ TRANSACTION : "payment via"
    APPOINTMENT_SESSION ||--o{ SESSION_PARTICIPANT : "includes"

    WALLET ||--o{ TRANSACTION : "records"

    SUBSCRIPTION_PLAN ||--o{ VENDOR_SUBSCRIPTION : "type for"
    VENDOR_SUBSCRIPTION ||--o{ SUBSCRIPTION_INVOICE : "billed via"
    VENDOR_SUBSCRIPTION }o--o| VOUCHER : "discounted by"
    VOUCHER ||--o{ VOUCHER_USAGE : "tracked in"
    VENDOR_SUBSCRIPTION ||--o{ VOUCHER_USAGE : "records"
```
