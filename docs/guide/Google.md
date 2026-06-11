
# Steps to Implement Google OAuth in the Frontend

## 1. Set Up Google Developer Console
- Go to the Google Developer Console (https://console.developers.google.com/)
- Create a new project or select an existing one
- Navigate to "Credentials" and create OAuth 2.0 Client ID
- Add authorized JavaScript origins (e.g., http://localhost:3000 for development)
- Add authorized redirect URIs where Google will send users after authentication
- Note your Client ID and Client Secret (these are already in your .env file)

## 2. Install Required Packages
- Install Google's authentication library in your frontend application
  - For React: `npm install @react-oauth/google` or `npm install react-google-login`
  - For other frameworks, use appropriate Google OAuth libraries

## 3. Create a Google Login Button
- Add a Google login button to your login form
- Configure the button with your Google Client ID
- Set up success and failure handlers

## 4. Handle Authentication Flow
- When a user clicks the Google login button, they'll be redirected to Google's authentication page
- After successful authentication, Google will return an access token
- Capture this access token in your success handler

## 5. Send Token to Your Backend
- Make a POST request to your `/api/user/google-login` endpoint
- Include the Google access token in the request body
- Process the response from your backend:
  - If 2FA is required, show the OTP input field
  - If authentication is successful, store the JWT tokens
