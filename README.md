# Juris - Legal Services Marketplace

A full-featured backend API for a legal services marketplace connecting clients with lawyers (and other legal professionals). Built with Django REST Framework, it handles everything from booking and escrew payments to real-time video consultations and subscription billing.

## Table of Contents

- [Overview](#overview)
- [Documentation](#documentation)
  - [Guides](#guides)
  - [System Diagrams](#system-diagrams)
  - [Postman Collections](#postman-collections)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Workflows](#workflows)
  - [System Flows](#system-flows)
  - [Client Journey](#client-journey)
  - [Lawyer/Vendor Journey](#lawyer--vendor-journey)
- [Application Modules](#application-modules)
- [API Overview](#api-overview)
- [Setup & Installation](#setup--installation)
- [Environment Variables](#environment-variables)
- [Management Commands](#management-commands)

## Overview

Juris is a marketplace where clients can discover and book appointments with legal professionals (lawyers, notaries, accountants, translators). The platform handles:

- Role-based user accounts (client vs. vendor)
- Multi-step vendor onboarding
- Appointment booking with Stripe payment processing and an escrow fund model
- Live audio/video consultations via Agora
- Lawyer subscription billing via Stripe
- KYC identity verification before fund withdrawal
- Real-time in-app notifications via WebSockets

## Documentation

Additional guides, diagrams, and Postman collections are available in the repository beside this [Readme.md](Readme.md)

### Guides

| File                                                     | Description                                                                                                                |
| -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| [docs/guide/Auth.md](docs/guide/Auth.md)                 | The auth system - JWT lifetimes, 2FA flow, rate limiting, password policy, CORS, and security middleware                   |
| [docs/guide/Subscription.md](docs/guide/Subscription.md) | Step-by-step guide for testing the subscription API - trial setup, payment methods, vouchers, webhooks, and notifications  |
| [docs/guide/Google.md](docs/guide/Google.md)             | Frontend integration guide for Google OAuth2 - how to wire up the login button and send the token to the backend           |
| [docs/guide/TRANSACTION.md](docs/guide/TRANSACTION.md)   | Appointment & transaction state machine - all status transitions for booking, escrow, completion, cancellation, and refund |

### System Diagrams

Full Mermaid diagrams (sequence, DFD, use case, ER) are in [Diagrams.md](Diagrams.md)

| Diagram           | What it shows                                                                               |
| ----------------- | ------------------------------------------------------------------------------------------- |
| Sequence Diagram  | Full appointment lifecycle - registration → booking → payment → consultation → fund release |
| Data Flow Diagram | Data flows across all 10 system processes, 7 external services, and 6 data stores           |
| Use Case Diagram  | All actors (Client, Lawyer, Admin) and their platform capabilities                          |
| ER Diagram        | Complete data model across all 8 Django apps (~20 entities and their relationships)         |

### Postman Collections

Ready-to-import collections are in the [`postman/`](postman/) folder. Import any file into Postman to get a pre-built request set for that area of the API.

| Collection                                                                                                  | Covers                                                    |
| ----------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| [Authentication API](postman/Authentication%20API%20Collection.postman_collection.json)                     | Register, login, 2FA, OTP, password reset, Google OAuth2  |
| [Vendor Profile API](postman/Vendor%20Profile%20API%20Collection.postman_collection.json)                   | 9-step vendor onboarding, profile management              |
| [Lawyer API](postman/Lawyer%20API%20Collection.postman_collection.json)                                     | Availability, appointments, wallet, withdrawals, KYC      |
| [Subscription Management API](postman/Subscription%20Management%20API%20Collection.postman_collection.json) | Plans, payment methods, vouchers, invoices, notifications |

## Features

### Authentication & Security

- Email + password registration and login
- Email verification (link sent on signup)
- Two-factor authentication (SMS OTP via Twilio)
- Google OAuth2 social login
- JWT access tokens + HttpOnly refresh token cookie
- Token blacklisting on logout
- Login attempt throttling with account lockout
- Password reset via email link or SMS OTP
- API rate limiting (configurable per anonymous/authenticated user)

### Vendor Onboarding

- Multi-step profile completion wizard (session-based, token-authenticated)
- Steps: category → business name → address → languages → avatar → legal info → additional info
- Cloudinary avatar upload (URL or file)
- Romanian bar association registry support
- Profile completion gated before marketplace access

### Lawyer Profiles & Availability

- Lawyer categories and subcategories
- Pricing plans (offerings) with per-30-min rates - each plan has an independent price and can be attached to specific time slots
- Service delivery types per offering: **Physical** (free, in-office), **Audio** (paid, phone), **Video** (paid, Agora RTC)
- Full overlap validation on save, the API rejects any slot that would conflict with an existing one on the same day

### Calendar & Scheduling API

The availability system is purpose-built to power a booking calendar on the frontend. Every read endpoint is accessible to any authenticated user so the client can render the lawyer's calendar before booking.

**Lawyer sets up their schedule:**

- Create weekly recurring slots: day of week + start/end time + pricing plan (e.g., Monday 09:00–17:00 on "Standard Plan")
- **Bulk create**: POST one set of times and apply it to multiple days at once (e.g., Mon–Fri 09:00–17:00 in one request)
- **Copy template**: copy all slots from one day to other days (e.g., clone Monday's schedule to Tuesday and Wednesday)
- Enable/disable individual slots without deleting them
- Clear all slots in one call, or clear only past unavailability entries

**Lawyer blocks out time (unavailability):**

- Block a specific date either **all-day** or as a **time range** (e.g., 14:00–16:00 on 2025-07-10)
- Typed reasons: `vacation`, `sick_leave`, `personal`, `court_appearance`, `meeting`, `training`, `other`
- Overlap detection prevents double-blocking the same time on the same date
- Filter by date range, type, or all-day flag
- Stats endpoint returns counts by type and the next upcoming block

**Frontend reads availability to render a calendar:**

The calendar API endpoint also automatically **crosses out unavailability**: any slot that overlaps with a block (all-day or time-range) on that date is removed from `available_slots` before the response is returned. The frontend never needs to do this filtering itself.

### Appointment Booking

- Full lifecycle: `pending → confirmed → completed` (or cancelled / no-show / rescheduled)
- Stripe PaymentIntent created at booking; appointment cancelled automatically if payment doesn't arrive within 10 minutes (Celery task)
- **Escrow model**: funds held as `PENDING` transaction until appointment completes
- Fund release only after appointment ends and is explicitly marked complete
- Rescheduling by either party (preserves confirmed status)
- Cancellation with configurable refund eligibility window (threshold hours per lawyer)
- Automatic Stripe refund processing with webhook confirmation

### Video & Audio Consultations

- Agora RTC token generation for in-session participants
- Session state tracking (`not_started → active → ended`)
- Separate participant records for lawyer and client

### Wallet & Withdrawals

- Per-lawyer wallet with running balance
- All fund movements tracked as typed transactions (payment, payout, refund, commission)
- Withdrawal requests require completed KYC verification
- Race-condition-safe balance deduction handeled
- Admin approval workflow for payouts

### Subscriptions

- Category-based subscription plans synced to Stripe Products/Prices
- 15-day trial period
- Trial-to-paid transition handled via webhooks
- Voucher system (percentage discount, fixed amount) with usage limits and expiry
- Concurrent voucher redemption protected with row-level locking
- Prorated billing, cancellation and reactivation
- Stripe dispute/chargeback detection with fund freeze

### KYC Verification

- Stripe Identity sessions for lawyer identity verification
- Verified status gates wallet withdrawals
- Webhook-driven status updates (verified / requires_input / cancelled / processing)

### Notifications

- In-app notification model with type-based routing
- Real-time delivery via Django Channels WebSocket consumers
- Notification types: trial ending, payment failed, appointment reminders, refund approved, withdrawal approved, and more
- Email notifications via SendGrid (subscription events, password reset, email verification)

## Tech Stack

| Layer                | Technology                                              |
| -------------------- | ------------------------------------------------------- |
| **Framework**        | Django 5.1 · Django REST Framework 3.15                 |
| **Language**         | Python 3.12                                             |
| **Database**         | PostgreSQL 17 (production) · SQLite (development)       |
| **Cache / Sessions** | Redis 7                                                 |
| **Async Tasks**      | Celery 5.5 + Redis broker                               |
| **Real-time**        | Django Channels 4.2 · Daphne 4.1 (ASGI)                 |
| **Payments**         | Stripe (appointments, subscriptions, refunds, disputes) |
| **Video / Audio**    | Agora RTC                                               |
| **SMS / OTP**        | Twilio                                                  |
| **Email**            | SendGrid                                                |
| **Media Storage**    | Cloudinary                                              |
| **Authentication**   | JWT (SimpleJWT) · Google OAuth2 · 2FA (SMS OTP)         |
| **API Docs**         | drf-yasg (Swagger / ReDoc)                              |
| **Containerisation** | Docker · Docker Compose                                 |

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                        Clients                           │
│              (Web / Mobile / Third-party)                │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP / WebSocket
                         ▼
┌──────────────────────────────────────────────────────────┐
│              Daphne (ASGI server) :8000                  │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              Django + DRF (REST API)                │ │
│  │  users · profiles · lawyer · lawyer_appointment     │ │
│  │  lawyer_wallet · subscriptions · kyc               │ │
│  └─────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────┐ │
│  │       Django Channels (WebSocket consumers)         │ │
│  └─────────────────────────────────────────────────────┘ │
└──────┬──────────────────┬──────────────────┬─────────────┘
       │                  │                  │
       ▼                  ▼                  ▼
┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐
│ PostgreSQL  │  │   Redis 7    │  │  Celery Worker        │
│ (primary DB)│  │ cache · OTP  │  │  (async tasks,        │
│             │  │ sessions     │  │   reminders,          │
│             │  │ WS layer     │  │   notifications)      │
└─────────────┘  └──────────────┘  └──────────────────────┘

External Services:
  Stripe - payments, subscriptions, refunds, KYC identity
  Agora  - RTC tokens for video/audio consultations
  Twilio - SMS OTP delivery
  SendGrid - transactional email
  Cloudinary - media/avatar storage
```

## Workflows

### System Flows

#### 1. User Registration & Login

```
Client/Vendor registers (email + password)
  └─ Verification email sent (SendGrid)
  └─ User clicks link → email verified

Login:
  └─ Credentials valid → access token + refresh cookie returned
  └─ If 2FA enabled → OTP sent via Twilio → verification required before token issued
  └─ Google OAuth2 → handled via social-auth-app-django
```

#### 2. Vendor Profile Completion

```
POST /api/profiles/session/start/          → returns session token
POST /api/profiles/steps/category/         → select professional category
POST /api/profiles/steps/business-name/    → set business name
POST /api/profiles/steps/address/          → set location
POST /api/profiles/steps/languages/        → select languages spoken
POST /api/profiles/steps/avatar/           → upload profile photo
POST /api/profiles/steps/legal-info/       → bar association, ID (lawyers only)
POST /api/profiles/steps/additional-info/  → bio, experience, social links
POST /api/profiles/complete/               → creates VendorProfile, unlocks dashboard
```

Each step validates the session token and asserts ownership using session.

#### 3. Appointment Booking & Escrow

```
Client browses lawyers → checks availability
  └─ POST /api/lawyer/appointment/         → creates Appointment (status=PENDING)
                                           → creates Transaction (type=PAYMENT, status=PENDING)
                                           → Stripe PaymentIntent created
                                           → Celery task: auto-cancel after 10 minutes if unpaid

Client completes payment in frontend
  └─ Stripe webhook: payment_intent.succeeded
       → appointment.status = CONFIRMED
       → Transaction stripe_id recorded
       → Funds held in escrow (Transaction stays PENDING)

Appointment occurs (physical / audio / video)

Either party marks appointment complete
  └─ POST /api/lawyer/appointment/{id}/complete/
       → validates appointment has actually ended (end_datetime <= now)
       → Transaction status = COMPLETED
       → wallet.balance += lawyer_amount  (with SELECT FOR UPDATE)
       → Lawyer can now withdraw
```

#### 4. Cancellation & Refund

```
Appointment cancelled (within refund window)
  └─ Stripe Refund created
  └─ Webhook: refund.created
       → Transaction status = COMPLETED (refund transaction)
       → Client notified

Stripe dispute opened (chargeback)
  └─ Webhook: charge.dispute.created
       → Pending payment transaction frozen (status = FAILED)
       → Lawyer and client notified
       → Admin alerted for manual review
```

#### 5. Subscription Billing

```
Vendor completes profile
  └─ Stripe Customer + Subscription created (trial_period_days=15)
  └─ Webhook: customer.subscription.created → VendorSubscription saved

Trial ends:
  └─ Webhook: customer.subscription.updated (status: trialing → active)
       → Listing activated, renewal date cached in Redis

Payment fails:
  └─ Webhook: invoice.payment_failed
       → Vendor listing deactivated, notification sent

Voucher applied:
  └─ POST /api/subscription/voucher/apply/
       → Voucher row locked (SELECT FOR UPDATE) to prevent over-use
       → Stripe coupon applied to subscription
```

#### 6. Video Consultation

```
Appointment type = VIDEO, status = CONFIRMED
  └─ GET /api/lawyer/appointment/{id}/session/token/
       → Agora RTC token generated (role: publisher for both parties)
       → Session record created / updated

Client and lawyer join using Agora SDK in frontend
Session ends → session.status = ENDED
```

#### 7. KYC & Withdrawal

```
Lawyer requests KYC:
  └─ POST /api/kyc/start/
       → Stripe Identity session created
       → Verification URL returned to frontend

Stripe webhook: identity.verification_session.verified
  └─ KYCVerification.is_verified = True
  └─ LawyerProfile.kyc_verification_status = "verified"

Lawyer requests withdrawal:
  └─ POST /api/lawyer/wallet/withdraw/
       → KYC verified? → yes
       → Wallet locked? → no
       → SELECT FOR UPDATE on wallet → re-check balance
       → Transaction (type=PAYOUT, status=PENDING) created
       → wallet.balance -= amount
       → Admin approves → payout processed
```

### Client Journey

#### Step 1 - Create an account

- Register with email, password, first name, last name, and phone number.
- A verification email is sent via SendGrid. The client clicks the link to activate their account.
- _(Optional)_ Sign in with Google OAuth2 - account is created automatically on first social login.

#### Step 2 - Log in

- Submit email and password.
- If **2FA is enabled**: an OTP is sent to the registered phone number via Twilio. The client submits the code to receive their JWT access token and refresh cookie.
- If **2FA is disabled**: tokens are issued immediately on valid credentials.
- After 5 failed attempts the account is locked for 30 minutes.

#### Step 3 - Browse and find a lawyer

- Search and filter the lawyer listing by category, subcategory, language, rating, and price.
- View a lawyer's public profile: bio, bar association, experience, offerings, and ratings.
- Check the lawyer's availability calendar for a specific date to see open slots and their prices.

#### Step 4 - Book an appointment

- Select a time slot and a service type:
  - **Physical** - in-office meeting (free)
  - **Audio** - phone consultation (paid)
  - **Video** - video call via Agora (paid)
- Submit the booking request. The system creates the appointment with status `PENDING` and generates a Stripe PaymentIntent.
- The client has **10 minutes** to complete payment. If the window expires, the appointment is automatically cancelled by a Celery task.

#### Step 5 - Pay

- The client completes the Stripe payment on the frontend using the PaymentIntent client secret.
- Stripe fires `payment_intent.succeeded` → the webhook confirms the appointment, setting its status to `CONFIRMED`.
- Money is held in **escrow** (the lawyer does not receive it yet).
- A reminder notification is sent 24 hours before the appointment starts.

#### Step 6 - Attend the appointment

**For a Video or Audio appointment:**

- The client requests an Agora RTC token from the API.
- Both the client and lawyer join the call using the Agora SDK in the frontend.
- The session is tracked (`not_started → active → ended`).

**For a Physical appointment:**

- The client goes to the lawyer's office at the booked time.

#### Step 7 - Reschedule (if needed)

- Either party can reschedule before the appointment starts.
- The appointment keeps its `CONFIRMED` status with `is_rescheduled = true` and a new datetime.
- The original payment is preserved; no new payment is required.

#### Step 8 - Mark as complete

- After the appointment ends, either the client or the lawyer calls the complete endpoint.
- The system validates that `end_datetime` has passed before allowing completion.
- The appointment moves to `COMPLETED` and the escrowed funds are released to the lawyer's wallet.

#### Step 9 - Cancel and get a refund (alternative path)

- The client can cancel a `CONFIRMED` appointment.
- If the cancellation happens before the lawyer's cancellation threshold window (e.g., 24 hours before), the client is eligible for a refund.
- The API triggers a Stripe refund automatically.
- Stripe fires `refund.created` → the webhook confirms the refund and notifies the client.
- If the cancellation is too late, no refund is issued.

#### Step 10 - Dispute (chargeback)

- If the client raises a dispute with their bank, Stripe fires `charge.dispute.created`.
- The pending payment transaction is frozen immediately to protect both parties.
- The lawyer and client are notified, and the case is flagged for manual admin review.

### Lawyer / Vendor Journey

#### Step 1 - Create an account

- Register with email, password, and phone number.
- Select **role: vendor** and **vendor type: lawyer** (or notary, accountant, translator) at signup.
- Verify the email address via the link sent to their inbox.

#### Step 2 - Log in

- Same as the client flow, including optional 2FA via SMS OTP.

#### Step 3 - Complete the vendor profile (onboarding method)

The platform uses a multi-step session-based method. Each step saves progress so the lawyer can resume later. All steps are authenticated and ownership-verified.

| #   | Step                        | What is saved                                   |
| --- | --------------------------- | ----------------------------------------------- |
| 1   | Start session               | Session token issued                            |
| 2   | Category                    | Professional category (e.g., Lawyer)            |
| 3   | Business name               | Display name on the marketplace                 |
| 4   | Address                     | Office location with coordinates                |
| 5   | Languages                   | Languages spoken with clients                   |
| 6   | Avatar                      | Profile photo (URL or file upload → Cloudinary) |
| 7   | Legal info _(lawyers only)_ | First/last name ID, email, bar association      |
| 8   | Additional info             | Bio, years of experience, website, social links |
| 9   | Complete                    | `VendorProfile` created, dashboard unlocked     |

#### Step 4 - Subscribe to the platform

- After profile completion, a Stripe Customer and Subscription are created automatically.
- The lawyer receives a **15-day free trial**.
- At trial end, Stripe charges the configured monthly fee. The lawyer's listing stays active while the subscription is `active` or `trialing`.
- A voucher code can be applied at any time to get a percentage or fixed discount.
- If a payment fails, the listing is deactivated until billing is resolved.

#### Step 5 - Set up pricing and availability

**Pricing plans (offerings):**

- Create one or more named pricing plans (e.g., "Standard Plan", "Weekend Premium").
- Each plan has a `price_per_30min` rate. Duration-based pricing is calculated automatically.
- Activate service delivery types per plan: Physical (free), Audio (paid), Video (paid).

**Availability schedule (powers the booking calendar):**

- Define recurring weekly slots - each slot is a day + time window + pricing plan (e.g., Monday 09:00–17:00 on "Standard Plan").
- Use **bulk create** to apply the same slot to multiple days in one request (e.g., set Mon–Fri 09:00–17:00 at once).
- Use **copy template** to clone an entire day's schedule to other days.
- The system rejects any overlapping slot on the same day at save time.

**Blocking out time (unavailability):**

- Block specific calendar dates - either all-day or a time range (e.g., 14:00–16:00 for a court appearance).
- Categorise each block: vacation, sick leave, personal, court appearance, meeting, training, or other.
- Past blocks can be cleared in bulk; a stats endpoint shows counts by type and the next upcoming block.

**How the frontend uses this:**

- The calendar endpoint (`/availability/calendar/`) returns one object per day in a date range. Each day has `available_slots`, `is_available`, and `total_hours`. Unavailability blocks are already subtracted - the frontend just renders what it receives.
- Tapping a day calls the single-date endpoint to show bookable slots with live pricing.
- Before submitting a booking, the frontend calls the time-check endpoint to confirm the slot is still free.

#### Step 6 - Complete KYC verification

- Before withdrawing any earnings, the lawyer must complete KYC.
- Initiate a Stripe Identity verification session from the dashboard.
- Stripe sends the lawyer through a document + selfie check.
- Stripe fires `identity.verification_session.verified` → KYC status is set to `verified`.
- Without verified KYC, all withdrawal requests are rejected.

#### Step 7 - Receive bookings

- Clients book slots from the lawyer's availability calendar.
- On payment confirmation, the lawyer sees the appointment as `CONFIRMED` in their dashboard.
- A 24-hour reminder notification is sent via WebSocket and stored in the notification centre.

#### Step 8 - Conduct the appointment

**Video / Audio:**

- The lawyer requests an Agora RTC token.
- Both parties join using the Agora SDK.
- The session state is tracked server-side.

**Physical:**

- The client arrives at the office at the agreed time.

#### Step 9 - Complete the appointment and receive funds

- After the appointment ends, the lawyer (or client) marks it as complete via the API.
- The system verifies the appointment has ended before releasing funds.
- The escrowed amount (minus platform commission) is credited to the lawyer's wallet instantly.
- A `COMPLETED` transaction record is created in the wallet ledger.

#### Step 10 - Withdraw earnings

- The lawyer submits a withdrawal request specifying an amount.
- Pre-conditions checked:
  1. KYC is verified
  2. Wallet is not locked
  3. Balance is sufficient (checked again under a row-level lock to prevent race conditions)
- A `PAYOUT` transaction is created with status `PENDING`.
- The balance is deducted immediately to prevent double withdrawal.
- An admin approves the payout and processes the bank transfer.
- The lawyer receives a notification when the withdrawal is approved.

#### Step 11 - Cancellation by lawyer

- The lawyer can cancel a confirmed appointment before it starts.
- Whether the client receives an automatic refund depends on the lawyer's configured cancellation threshold.
- The lawyer is notified and the appointment is marked `CANCELLED`.

## Application Modules

| App                   | Responsibility                                                                                   |
| --------------------- | ------------------------------------------------------------------------------------------------ |
| `users`               | Custom user model, auth (JWT, 2FA, Google OAuth2), email/phone verification, password management |
| `profiles`            | Vendor profile wizard, VendorProfile, Address, Categories, Languages, Certificates, Media        |
| `lawyer`              | LawyerProfile, LawyerOffering (pricing plans), OfferingType (physical/audio/video), categories   |
| `lawyer_availability` | Weekly availability slots, unavailability periods, conflict detection                            |
| `lawyer_appointment`  | Appointment CRUD, Stripe payment orchestration, session management, refunds                      |
| `lawyer_wallet`       | Wallet model, transaction ledger, withdrawal requests                                            |
| `subscriptions`       | SubscriptionPlan, VendorSubscription, Voucher, Stripe webhook handler, in-app notifications      |
| `kyc`                 | KYCVerification model, Stripe Identity integration                                               |

## API Overview

Interactive documentation is available at runtime:

| URL             | Description        |
| --------------- | ------------------ |
| `/swagger/`     | Swagger UI         |
| `/redoc/`       | ReDoc UI           |
| `/swagger.json` | Raw OpenAPI schema |

### Endpoint Groups

| Prefix                                             | Module                                            |
| -------------------------------------------------- | ------------------------------------------------- |
| `POST /api/user/register/`                         | Registration                                      |
| `POST /api/user/login/`                            | Login (returns JWT)                               |
| `POST /api/user/token/refresh/`                    | Refresh access token                              |
| `POST /api/user/logout/`                           | Blacklist refresh token                           |
| `POST /api/user/2fa/toggle/`                       | Enable / disable 2FA                              |
| `POST /api/user/verify-2fa/`                       | Verify OTP during login or setup                  |
| `GET/PATCH /api/user/profile/`                     | Current user profile                              |
| `POST /api/profiles/session/start/`                | Begin vendor onboarding                           |
| `POST /api/profiles/steps/*/`                      | Onboarding steps                                  |
| `POST /api/profiles/complete/`                     | Finish onboarding                                 |
| `GET /api/lawyer/`                                 | List / search lawyers                             |
| `GET /api/lawyer/availability/weekly/`             | Weekly schedule grouped by day name               |
| `GET /api/lawyer/availability/calendar/`           | Per-day calendar for a date range (up to 90 days) |
| `GET /api/lawyer/availability/<lawyer_id>/<date>/` | Available slots for a single date                 |
| `POST /api/lawyer/availability/check-time/`        | Check if a specific time window is free           |
| `GET /api/lawyer/availability/by-offering/`        | Slots grouped by pricing plan                     |
| `GET /api/lawyer/availability/`                    | CRUD - list/create availability slots             |
| `GET/PUT/DELETE /api/lawyer/availability/<id>/`    | CRUD - single slot                                |
| `POST /api/lawyer/availability/bulk-create/`       | Create same slot across multiple days             |
| `POST /api/lawyer/availability/copy-template/`     | Clone one day's schedule to other days            |
| `DELETE /api/lawyer/availability/clear-all/`       | Remove all slots (lawyer only)                    |
| `GET /api/lawyer/unavailability/`                  | List / create unavailability blocks               |
| `GET/PUT/DELETE /api/lawyer/unavailability/<id>/`  | Single unavailability entry                       |
| `GET /api/lawyer/unavailability/stats/`            | Counts by type + next upcoming block              |
| `DELETE /api/lawyer/unavailability/clear-past/`    | Remove past blocks                                |
| `POST /api/lawyer/appointment/`                    | Book appointment                                  |
| `GET /api/lawyer/appointment/{id}/`                | Appointment details                               |
| `POST /api/lawyer/appointment/{id}/cancel/`        | Cancel appointment                                |
| `POST /api/lawyer/appointment/{id}/reschedule/`    | Reschedule                                        |
| `POST /api/lawyer/appointment/{id}/complete/`      | Mark complete & release funds                     |
| `GET /api/lawyer/appointment/{id}/session/token/`  | Agora RTC token                                   |
| `GET /api/lawyer/wallet/`                          | Wallet balance                                    |
| `POST /api/lawyer/wallet/withdraw/`                | Request withdrawal                                |
| `GET /api/lawyer/wallet/transactions/`             | Transaction history                               |
| `POST /api/subscription/subscribe/`                | Create subscription                               |
| `POST /api/subscription/voucher/apply/`            | Apply voucher                                     |
| `GET /api/subscription/status/`                    | Subscription status                               |
| `POST /api/kyc/start/`                             | Start KYC verification                            |
| `GET /api/kyc/status/`                             | KYC status                                        |
| `POST /stripe/webhook/`                            | Stripe webhook receiver                           |

## Setup & Installation

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)
- A Stripe account (test keys are fine to start)
- A Twilio account (for SMS OTP)
- A SendGrid account (for email)

### 1. Clone the repository

```bash
git clone https://github.com/your-username/juris-backend.git
cd juris-backend
```

### 2. Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` and fill in your credentials. See [Environment Variables](#environment-variables) for the full reference.

### 3. Build and start all services

**Linux / macOS:**

```bash
docker compose up --build
```

**Windows (Docker Desktop with WSL2):**

```powershell
docker compose up --build
```

This starts five containers:

| Container          | Role                                     |
| ------------------ | ---------------------------------------- |
| `juris_backend`    | Django / Daphne ASGI server on port 8000 |
| `juris_postgres`   | PostgreSQL 17 database                   |
| `juris_redis`      | Redis 7 cache, channel layer, OTP store  |
| `juris_celery`     | Celery async worker                      |
| `juris_stripe_cli` | Stripe CLI for local webhook forwarding  |

Migrations and `collectstatic` run automatically on container start.

### 4. Load initial data

```bash
# Creates Category and Language seed data
docker compose exec web python manage.py load_initial_data

# Creates Stripe Products and syncs subscription plans
docker compose exec web python manage.py setup_stripe_products
```

### 5. Create a superuser

```bash
docker compose exec web python manage.py createsuperuser
```

### 6. Access the application

| URL                              | Description        |
| -------------------------------- | ------------------ |
| `http://localhost:8000/swagger/` | API documentation  |
| `http://localhost:8000/admin/`   | Django admin panel |
| `http://localhost:8000/api/`     | REST API root      |

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values. Key variables:

| Variable                                   | Description                                        |
| ------------------------------------------ | -------------------------------------------------- |
| `DJANGO_SECRET_KEY`                        | Django secret key (generate a long random string)  |
| `DEBUG`                                    | `True` for development, `False` for production     |
| `DJANGO_SETTINGS_MODULE`                   | Must be `juris.settings`                           |
| `POSTGRES_DB/USER/PASSWORD`                | PostgreSQL credentials                             |
| `STRIPE_SECRET_KEY`                        | Stripe secret key (`sk_test_...` or `sk_live_...`) |
| `STRIPE_WEBHOOK_SECRET`                    | Stripe webhook signing secret (`whsec_...`)        |
| `TWILIO_ACCOUNT_SID`                       | Twilio Account SID                                 |
| `TWILIO_AUTH_TOKEN`                        | Twilio Auth Token                                  |
| `TWILIO_PHONE_NUMBER`                      | Twilio phone number for sending SMS                |
| `SENDGRID_API_KEY`                         | SendGrid API key                                   |
| `AGORA_APP_ID`                             | Agora App ID                                       |
| `AGORA_APP_CERTIFICATE`                    | Agora App Certificate                              |
| `CLOUDINARY_CLOUD_NAME/API_KEY/API_SECRET` | Cloudinary credentials                             |
| `SOCIAL_AUTH_GOOGLE_OAUTH2_KEY/SECRET`     | Google OAuth2 credentials                          |
| `JWT_SIGNING_KEY`                          | Separate signing key for JWT tokens                |
| `FRONTEND_URL`                             | Your frontend origin URL (used in email links)     |

See `.env.example` for the full list with default values.

## Management Commands

```bash
# Load seed data (categories, languages)
python manage.py load_initial_data

# Sync subscription plans to Stripe
python manage.py setup_stripe_products

# Send trial-ending and renewal notifications manually
python manage.py check_subscriptions

# Delete expired profile completion sessions
python manage.py cleanup_sessions
```

## Notes

- **Stripe CLI** is included in `docker-compose.yml` for local webhook testing. It forwards Stripe events to `web:8000/stripe/webhook/` automatically.
- In **development** (`DEBUG=True`), SQLite is used. Switch to PostgreSQL for staging and production by setting `DEBUG=False` and providing Postgres credentials.
- The project uses **`python-decouple`** to read all configuration from `.env`. Never hardcode credentials.
