# Need a ride? Enjoy 40% off your next 2 trips

## Summary

This is a promotional email from Uber offering a 40% discount on the recipient's next two trips. The email consists almost entirely of CSS styling code and media queries for responsive design, with minimal actual content visible in the source. This type of heavily-styled HTML email is common in marketing campaigns and requires careful handling in Deek to properly extract the actual offer details and recipient information.

## Email Structure Analysis

### Technical Composition

1. **CSS Framework**: The email uses extensive media queries targeting different screen sizes (650px, 640px, 440px, 430px, 350px breakpoints)
2. **Custom Fonts**: Uber's proprietary font family (UberMove and UberMoveText variants) loaded via @font-face declarations
3. **Responsive Design Classes**: Multiple conditional styling classes (.show670, .hide430, .t1of12, etc.) for mobile/desktop rendering
4. **Content Location**: Actual promotional content is likely embedded below the CSS block (truncated in source)

### Key CSS Patterns Identified

The styling reveals several content types the email likely contains:

- **Offer tags** (.p13_mm_offer_tag): Highlighting the discount percentage
- **Pricing displays** (.p13_mm_discounted_price, .p13_mm_original_price): Before/after pricing
- **Merchant grids** (.gr_3_merchant, .gr_4_merchant): Possibly multiple offer displays
- **Deal layouts** (.p13n_deal_l_d_16, .p13n_deal_l_d_24): Promotional content containers

## Processing in Deek

### Step 1: Content Extraction

When processing this email type in Deek:

1. Strip all CSS blocks (everything between `<style>` tags or in @media queries)
2. Locate the actual HTML body content (typically follows the CSS)
3. Extract text from table cells, divs, and paragraph elements
4. Identify the core offer: "40% off your next 2 trips"

### Step 2: Key Data Points to Capture

- **Sender**: Uber (based on font references and domain)
- **Offer Type**: Percentage discount
- **Discount Amount**: 40%
- **Trip Quantity**: 2 trips
- **Promo Code**: Check for embedded codes in truncated content
- **Expiration Date**: Verify in full email body
- **Terms & Conditions**: Usually linked at bottom

### Step 3: Classification Tags

Apply these Deek tags:
- Category: `promotional`
- Sender: `uber`
- Type: `discount_offer`
- Industry: `rideshare`
- Action Required: `optional` (user can choose to use promo)

## Common Pitfalls

⚠️ **Warning: Truncated Content**  
The source provided is incomplete (ends mid-declaration at "@font-face{font-family: 'UberMoveT"). Always ensure you have the complete email before finalizing extraction.

⚠️ **CSS Noise Ratio**  
Emails with >90% CSS content can cause parser errors. Configure extraction rules to ignore style blocks entirely and focus on semantic HTML elements.

⚠️ **Dynamic Content**  
Uber emails often contain personalized discount amounts or trip credits. Don't assume all users received 40% off - check for template variables or user-specific values.

⚠️ **Link Extraction**  
Call-to-action buttons are typically styled divs or table cells. Extract `href` attributes from nested `<a>` tags, not from the visible button styling.

## Validation Checklist

Before marking this email as processed:

- [ ] Confirm offer amount (40%) matches any promo codes found
- [ ] Verify trip quantity limit (2 trips)
- [ ] Extract expiration timestamp
- [ ] Capture tracking parameters from links
- [ ] Document any geographic restrictions
- [ ] Note minimum purchase requirements if present

## Related Topics

- **[HTML Email Parsing Best Practices]** - Techniques for extracting content from heavily-styled marketing emails
- **[Uber Email Templates]** - Common patterns in Uber's email communications
- **[Promotional Code Extraction]** - How to identify and validate discount codes
- **[Responsive Email Detection]** - Understanding media queries and mobile-first design
- **[Marketing Email Classification]** - Tagging and categorizing promotional content

---

*Last updated: Based on Uber email template v2024*  
*Contact NBNE Ops if you encounter parsing errors with this email type*