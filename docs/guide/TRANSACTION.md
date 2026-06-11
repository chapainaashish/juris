## Complete Appointment and Refund Flow

**1. Client Books Appointment**
- Client selects lawyer, time slot, and appointment type
- New appointment row created: `status=PENDING`
- Payment transaction created: T1 with `type=PAYMENT`, `status=PENDING`, `wallet=lawyer_wallet`
- Client completes Stripe payment
 
**2. Payment Successful**
- Stripe webhook confirms payment
- Appointment updated: `status=CONFIRMED`
- Transaction T1 remains: `status=PENDING` (money held in escrow, not yet available to lawyer)

**3A. Appointment Completed Successfully**
- Appointment updated: `status=COMPLETED`
- Transaction T1 updated: `status=COMPLETED` (funds now available in lawyer's wallet)
- Lawyer can withdraw earnings

**3B. Client Reschedule Appointment**
- Appointment updated: `status=RESCHEDULED`, `is_rescheduled=True` with new date and time other details

**3C. Client Cancels Appointment**
- Appointment updated: `status=CANCELLED`, `refund_status=PENDING`
- Transaction T1 updated: `status=CANCELLED` (original payment cancelled)
- New refund transaction created: T2 with `type=REFUND`, `status=PENDING`, `wallet=null`

**4. Admin Reviews Refund Request**
- Admin sees appointment with `refund_status=PENDING`
- **If Admin Approves:**
  - Appointment updated: `refund_status=APPROVED`
  - System processes Stripe refund
  - Transaction T2 updated: `stripe_transaction_id=stripe_refund_id`
- **If Admin Rejects:**
  - Appointment updated: `refund_status=REJECTED`
  - Transaction T2 marked as `CANCELLED`

**5. Stripe Refund Processing**
- **If Stripe Refund Succeeds:**
  - Stripe webhook received
  - Transaction T2 updated: `status=COMPLETED`
  - Client receives money back
- **If Stripe Refund Fails:**
  - Transaction T2 updated: `status=FAILED`
  - Admin manually intervenes to resolve


NOTE: These steps are more concerned with status attributes and flow of transactions and appointment. Beside these attributes, other necessary and relevant attributes will also be updated which are not mentioned above for simplicity.