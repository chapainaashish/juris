# Authentication System Detailed Implementation

## User Authentication Flow
- Email/password login with JWT token authentication
- Access tokens valid for 600 minutes (10 hours)
- Refresh tokens valid for 1 day with automatic rotation
- Custom user model with email as primary identifier
- JWT token blacklisting for enhanced security after rotation
- Configurable token lifetimes via environment variables

## Email Verification
- Verification links valid for 48 hours (configurable)
- Automatic resending of verification emails if previous link expired(while login)
- Secure token generation using Django's token generator
- Redirect to configurable success/failure URLs
- Console email backend for development, SendGrid for production

## Two-Factor Authentication (2FA)
- Optional SMS-based 2FA that users can toggle on/off
- 6-digit numeric OTP codes
- OTP valid for exactly 5 minutes before expiring
- Clear OTP state after successful verification
- Automatic initialization of 2FA flow during login
- Session-based OTP handling
- Prevention of OTP brute force attacks via attempt limiting

## Security Rate Limiting
- Maximum 5 failed OTP attempts before account lockout
- 30-minute lockout period after exceeding maximum attempts
- 60-second cooldown between OTP resend requests
- Password attempt tracking to prevent brute force attacks
- API-level rate limiting: 20 requests/minute for anonymous users
- API-level rate limiting: 60 requests/minute for authenticated users

## Browser Security Enhancements
- XSS protection via Django's security middleware
- Content-type sniffing prevention for safer file uploads
- HTTP-only cookies to prevent JavaScript access to session data
- SameSite=Lax cookie policy to mitigate CSRF attacks
- Configurable session timeout (12 hours by default)

## Password Policy Enforcement
- Minimum 10-character password requirement
- Similarity check against user attributes (max 70% similarity)
- Common password detection to prevent weak password use
- Numeric-only password prevention for stronger credentials

## Google OAuth Integration
- Automatic email verification for Google-authenticated users
- 2FA enforcement for Google accounts if enabled on user profile
- Consistent JWT token generation across all authentication methods
- Social authentication pipeline for custom user creation/linking

## OTP Implementation Details
- SMS delivery using Twilio API (configured for production mode)
- Development mode fallback that prints OTP to console
- Debug/Production environment switching
- Session-based tracking of authentication state
- Configurable OTP code length (6 digits by default)

## CORS Security Controls
- Environment-specific CORS settings
- Development: all origins allowed for easy testing
- Production: strict origin list with explicit configuration
- Credentials allowed for authentication support

## File Upload Security
- 5MB maximum file size limit for uploads
- Restricted file permissions (0644) for uploaded content
- Dedicated media directory with controlled access

## Phone Number Management
- Phone number uniqueness enforcement
- Update capability with duplicate checking
- Required for enabling 2FA
- International phone number format support

## Response Handling
- Consistent JSON response structure
- Detailed error messages with remaining attempts count
- Accurate HTTP status codes based on error type
- Proper error handling for every authentication scenario

## Environment Configuration
- All sensitive parameters configurable via environment variables
- Database connection configurable between SQLite and PostgreSQL
- SendGrid email service configuration
- Twilio integration configuration


