# SEO Meta Tags, DNS Changes, and Image Dimensions

This article addresses three common client queries that often arrive together during website setup: the correct format for SEO meta tag content, the steps required after DNS A record changes are completed, and the standard image dimensions for Cairn sites. These questions typically come from marketing teams preparing content for launch.

## SEO Meta Tag Text Format

### Keywords Meta Tag

For the `keywords` meta tag, use comma-separated values with a space after each comma:

```
Dementia support, Dementia services, Memory care, Nursing home
```

**Best practices:**
- 5-10 keywords maximum
- Use natural phrases, not single words where possible
- Include location-specific terms if relevant
- Avoid keyword stuffing

### Description Meta Tag

Write as a natural sentence or two (150-160 characters):

```
Specialist dementia support and nursing services in Northumberland. Compassionate care from experienced professionals.
```

### Title Tag

Write as a clear phrase with separators (50-60 characters):

```
Dementia Support Services | Company Name
```

> **Note:** Modern SEO best practice considers the keywords meta tag largely obsolete for ranking purposes. Focus effort on well-written title and description tags instead.

## DNS A Record Changes - Post-Configuration Steps

When a client reports their A record has been updated and the domain now resolves correctly (e.g., "demnurse.com goes to A! Gardening"), you must complete the server-side configuration.

### Steps Required

1. **Verify DNS propagation**
   - Check the domain resolves to the correct IP using `nslookup` or `dig`
   - Confirm with client when they made the change (allow up to 48 hours for full propagation)

2. **Add domain to Apache/nginx configuration**
   - Add the new domain as a ServerAlias in the relevant VirtualHost configuration
   - Include both www and non-www variants if required

3. **Update Cairn site settings**
   - Log into Cairn admin
   - Navigate to Site Settings → Domain Configuration
   - Add the new domain to the permitted domains list
   - Set as primary domain if appropriate

4. **Configure SSL certificate**
   - Generate/update Let's Encrypt certificate to include new domain
   - Test HTTPS is working: `https://newdomain.com`

5. **Test and confirm**
   - Clear any caching (CDN, server-side, browser)
   - Check all pages load correctly on new domain
   - Verify assets (images, CSS, JS) load properly
   - Confirm with client

> **Warning:** Sites will not load on the new domain until you complete the VirtualHost configuration, even if DNS is pointing correctly. Don't leave clients waiting - this is a priority task.

### Common Pitfalls

- **Mixed protocol issues**: If site was on HTTPS previously, ensure redirects are in place
- **Hardcoded URLs**: Check for absolute URLs in content that reference old domain
- **Session cookies**: May need to clear for admin access on new domain

## Image Dimensions for Cairn Sites

Standard image dimensions vary by template and placement. Provide clients with these specifications:

### Hero/Banner Images
- **Dimensions:** 1920 × 1080px (minimum)
- **Aspect ratio:** 16:9
- **Format:** JPG (optimised) or WebP
- **Max file size:** 500KB

### Featured/Thumbnail Images
- **Dimensions:** 800 × 600px
- **Aspect ratio:** 4:3
- **Format:** JPG or PNG
- **Max file size:** 200KB

### Logo
- **Dimensions:** 400 × 200px (maximum height)
- **Format:** PNG with transparency preferred
- **Max file size:** 100KB

### Content Images
- **Dimensions:** 1200px wide (maximum)
- **Format:** JPG (optimised)
- **Max file size:** 300KB

### General Guidelines

- Always provide images larger than display size - Cairn will resize down
- Use 72 DPI for web (not print resolution)
- Compress images before upload using tools like TinyPNG or ImageOptim
- Modern formats (WebP, AVIF) preferred if browser support allows

> **Tip:** Create a template dimensions document customised for each client's specific template. Different Cairn themes may have different optimal sizes.

## Related Topics

- **DNS Configuration Guide** - Comprehensive DNS setup instructions
- **SSL Certificate Management** - Let's Encrypt configuration and renewal
- **Cairn Site Settings** - Complete admin interface guide
- **Image Optimisation Best Practices** - Compression and format selection
- **VirtualHost Configuration** - Apache/nginx setup for multiple domains
- **SEO Best Practices for Cairn Sites** - Complete on-page SEO guide