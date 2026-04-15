# Colourbyte Order Delivery Notification (10:13 - 11:13 Delivery Window)

This article covers the standard DPD delivery notification email for Colourbyte orders, which provides a specific one-hour delivery window on the day of delivery. These emails are automated notifications sent by DPD Local on behalf of Colourbyte and contain critical delivery information including the precise time window, driver name, parcel tracking number, and recipient options if unavailable during delivery.

## Email Identification

**From:** DPD / Colourbyte (via DPD notification system)  
**Subject format:** "Your Colourbyte order will be delivered today between [TIME] - [TIME]"  
**Delivery provider:** DPD Local  
**Typical advance notice:** Sent morning of delivery day

## Key Information Contained

1. **Delivery date:** Specified as "TODAY" with full date (e.g., "14th April 2026")
2. **Time window:** One-hour slot (e.g., 10:13 - 11:13)
3. **Driver name:** Named driver assignment (e.g., "Paul")
4. **Parcel tracking number:** Format appears as four groups of numbers (e.g., "1597 6979 228 492")
5. **Delivery options:** Link to "Show my options" if recipient unavailable

## Standard Workflow for NBNE Operators

### 1. Verify Delivery Expectations

- Cross-reference the tracking number against any open Colourbyte purchase orders in Cairn
- Confirm the delivery address matches the intended NBNE location
- Check if the time window conflicts with site access restrictions or planned outages

### 2. Ensure Site Readiness

- Notify reception/security of incoming delivery within the specified window
- Ensure authorized personnel are available to receive and sign for the parcel
- If the delivery window is impractical, use the "Show my options" link immediately to:
  - Reschedule delivery
  - Redirect to alternative address
  - Arrange safe place delivery (if appropriate)

### 3. Track Parcel Progress

- Download the DPD app or use the web tracking portal with the provided tracking number
- Real-time driver tracking typically becomes available 30-60 minutes before the window
- Driver name (e.g., "Paul") can help identify the correct delivery person on-site

### 4. Post-Delivery Actions

- Log receipt in Cairn asset management system
- File the tracking number with the associated purchase order
- Update any relevant work orders or project tickets

## Common Pitfalls

⚠️ **Warning:** The one-hour delivery window is relatively firm but not guaranteed. Allow ±15 minutes margin for driver scheduling variations.

⚠️ **Warning:** The "Show my options" link may have time restrictions. Delivery changes typically must be made at least 1 hour before the window begins.

⚠️ **Warning:** Email contains significant HTML/CSS formatting code at the top. When forwarding or copying information, extract only the relevant delivery details to avoid confusion.

⚠️ **Critical:** DPD Local drivers may not have extended wait times. If you cannot receive during the window, proactively reschedule rather than hoping for redelivery.

## Technical Notes on Email Structure

This email uses MJML framework (evidenced by `.mj-` CSS classes) and is heavily formatted for cross-platform compatibility. The actual delivery information is embedded within extensive HTML markup. When parsing these emails programmatically or copying details:

- Ignore CSS/styling code at document start
- Focus on plaintext content sections
- Extract tracking number carefully (spaces are part of the format)
- Preserve time window exactly as stated

## Preferences and App Features

The email promotes the DPD app and preference management. For NBNE sites with regular Colourbyte deliveries:

- Consider setting up a site-specific DPD account
- Save delivery preferences (e.g., safe place, authority to leave)
- Use "Update Preferences" link to establish defaults for future deliveries
- This reduces manual intervention for each delivery

## Vendor Information

**Colourbyte:** Equipment/component supplier  
**DPD Local:** Last-mile delivery service, part of DPD UK network  
**Environmental note:** DPD promotes "Net Zero by 2040" initiative mentioned in email footer

## Related Topics

- **[Cairn Asset Management] - Receiving and Logging Equipment Deliveries**
- **[Vendor Management] - Colourbyte Supplier Profile and Standard Lead Times**
- **[Site Access Procedures] - Coordinating Third-Party Deliveries**
- **[DPD Tracking Integration] - Automated Parcel Status Updates**
- **[Purchase Order Fulfillment] - Closing POs Upon Receipt**

---

*Last updated: [Date] | Maintained by: NBNE Operations Team*