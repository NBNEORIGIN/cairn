# Reminder: TEST CLASS — tomorrow at 09:00

This is an automated booking reminder email sent to clients 24 hours before their scheduled appointment. The email confirms key booking details including service type, provider, date, time, duration, price, and reference number. It also provides cancellation/rescheduling instructions and includes standard footer text identifying the sender and email purpose.

## Email Structure

### 1. Subject Line
```
Reminder: [SERVICE NAME] — tomorrow at [TIME]
```
- Uses dynamic merge fields for service name and appointment time
- "tomorrow" indicates this is sent exactly 24 hours prior to the appointment
- Time format uses 24-hour clock without leading zero for single-digit hours (e.g., "09:00")

### 2. Personalization
```
Dear [client_first_name] [client_last_name],
```
- Uses lowercase formatting for client name in this example ("toby fletcher")
- **WARNING:** Check if this lowercase formatting is intentional or a template bug that needs fixing

### 3. Booking Details Block
The core information block includes:

- **Service:** Name of the booked service (e.g., "TEST CLASS")
- **With:** Provider/instructor name (e.g., "Chrissie Howard")
- **Date:** Full date format - Day, DD Month YYYY
- **Time:** 24-hour format (HH:MM)
- **Duration:** Specified in minutes
- **Price:** Currency symbol and amount
- **Reference:** Booking reference with hash prefix (e.g., "#47")

### 4. Cancellation Information
Standard text directing clients to contact NBNE if they need to cancel or reschedule. This section does not include:
- Direct cancellation links
- Self-service portal URLs
- Specific contact methods (phone/email)

**COMMON PITFALL:** Clients may not know HOW to contact you based on this email alone. Ensure your booking confirmation email (sent at time of booking) contains full contact details.

### 5. Footer Text
Two-part footer:
1. Business identifier and sign-off
2. Email classification text explaining why the client received this and distinguishing it from marketing communications

## Timing and Automation

- **Trigger:** Sent automatically 24 hours before appointment start time
- **Time zone:** Appears to use the business's local time zone
- **Subject line logic:** Uses "tomorrow" when sent 24 hours prior (verify how this handles overnight bookings or different time zones)

## System Integration Notes

This email references:
- **Client database:** First name, last name
- **Booking system:** Service name, reference number, date/time, duration, price
- **Staff/resource database:** Provider name ("Chrissie Howard")
- **Business settings:** Business name ("NBNE Business Platform"), currency settings

## Common Issues and Troubleshooting

### Client Not Receiving Reminders
1. Check spam/junk folder settings
2. Verify client email address in booking record
3. Confirm automation is enabled for reminder emails
4. Check 24-hour send window hasn't been missed (if booking made <24hrs before appointment)

### Incorrect Information Displayed
- **Wrong provider:** Check resource assignment in booking record
- **Wrong price:** Verify service pricing hasn't changed since booking was made (should display original booking price, not current price)
- **Wrong time:** Check time zone settings for both client and business

### Customization Requests
If clients request different reminder timing (e.g., 48 hours instead of 24 hours), check if Deek supports:
- Multiple reminder schedules
- Per-service reminder settings
- Per-client reminder preferences

## Template Customization Points

Operators may want to customize:
- **Cancellation policy details:** Add specific timeframes or fees
- **Contact methods:** Include phone number, email, or portal link
- **Preparation instructions:** Service-specific details (what to bring, dress code, etc.)
- **Location information:** Address, parking, or access instructions
- **Pre-appointment forms:** Links to intake forms or waivers

## Related Topics

- **Booking Confirmation Email** - Initial email sent when booking is created
- **Cancellation Policy Configuration** - Setting up cancellation windows and fees
- **Email Template Management** - How to edit automated email content
- **Client Communication Preferences** - Managing opt-ins and notification settings
- **No-Show Management** - Handling clients who don't attend after receiving reminders
- **Time Zone Handling** - How Deek manages appointments across different time zones