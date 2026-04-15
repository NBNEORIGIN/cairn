# Identifying and Handling SGS Engineering Promotional Emails

## Summary
SGS Engineering promotional emails are recurring marketing communications that target NBNE mailboxes, often advertising tool sales and discounts. These emails are characterized by extensive tracking URLs, image-heavy layouts, and promotional content unrelated to NBNE operations. This article provides guidance on identifying these emails, understanding why they appear, and taking appropriate action to minimize their impact on operational efficiency.

## Identification Characteristics

### 1. Subject Line Patterns
- Personalized greetings (e.g., "Toby, Save Up To...")
- Percentage-based discount claims (35% Off, etc.)
- Seasonal promotional language ("This Spring")
- Reference to "SGS" or "SGS Engineering"

### 2. Technical Indicators
- **Domain**: Emails originate from exponea.com CDN infrastructure
- **Multiple tracking URLs**: Body contains numerous long, encoded URLs containing tracking parameters
- **URL structure**: Links follow pattern `cdn.uk.exponea.com/sgsengineeringprod/e/.eJw...`
- **Fallback text**: "Can't see this email? View in browser" header
- **Image-heavy content**: Minimal text, primarily image placeholders in plain text view

### 3. Content Markers
- Product categories: Tool chests, engineering supplies, workshop equipment
- Navigation elements: Home, category links
- Marketing automation footprint (Exponea platform)

## Root Cause Analysis

These emails typically reach NBNE mailboxes due to:

1. **Legacy supplier relationships**: Historical procurement accounts that were never deactivated
2. **Shared contact databases**: Personal email addresses used for work purposes previously
3. **Auto-forwarding rules**: Misconfigured email rules routing external mail to internal systems
4. **Mailing list persistence**: B2B marketing lists that retain contacts indefinitely

## Recommended Actions

### Immediate Response
1. **Do not click links** - Tracking URLs confirm active email addresses and increase future volume
2. **Mark as spam/junk** - Train your mail filter without engaging with content
3. **Delete without opening images** - Prevents read receipts and tracking pixels from activating

### Long-term Remediation
1. **Locate unsubscribe mechanism**:
   - View email in browser using provided link
   - Scroll to footer for unsubscribe option
   - Process unsubscribe request (expect 7-10 day processing time)

2. **Update mail filters**:
   - Create rule blocking `@exponea.com` sender domains
   - Add "SGS Engineering" keyword filters
   - Route future matches directly to junk folder

3. **Audit supplier contacts**:
   - Review which external vendors have your NBNE email
   - Request removal from marketing lists while maintaining transactional communications
   - Provide alternative contact methods for non-critical vendor communications

### For System Administrators
1. **Implement domain-level filtering** for known marketing automation platforms
2. **Review SPF/DMARC policies** to reduce spoofing risk
3. **Audit mail forwarding rules** across user accounts to identify misconfigurations

## Common Pitfalls

⚠️ **Warning**: Do not reply to these emails requesting removal. Reply addresses often go to unmonitored inboxes and confirm your email is active.

⚠️ **Warning**: Clicking "view in browser" links, even to unsubscribe, validates tracking parameters. Use browser privacy mode if you must access unsubscribe functions.

⚠️ **Pitfall**: Setting aggressive spam filters without exceptions may block legitimate supplier communications. Maintain whitelist for known operational contacts.

⚠️ **Pitfall**: Using personal email addresses for vendor accounts creates persistent cross-contamination between personal and work communications.

## Verification Process

If uncertain whether an email is legitimate operational communication versus marketing:

1. Check **Cairn procurement records** for active SGS Engineering relationships
2. Verify with **your supervisor** if SGS is an approved supplier
3. Contact **sender directly** using independently verified contact information (not reply address)
4. Review **previous email history** for transactional patterns versus purely promotional content

## Documentation

When these emails persist despite remediation:

- Log incidents in **Cairn ticketing system** under category: Email/Spam
- Include full email headers for IT analysis
- Note frequency and any pattern changes
- Track whether multiple team members receive identical messages

## Related Topics

- **Email Security Best Practices** - General guidance on identifying phishing and spam
- **Vendor Communication Protocols** - Approved channels for supplier interactions
- **Mail Filter Configuration** - User-level email management settings
- **Data Privacy and Marketing Compliance** - GDPR and B2B communication rights
- **Procurement Contact Management** - Maintaining separation between operational and marketing communications