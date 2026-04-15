# NBNE Google Ads — Lessons Learned

**Author:** Toby Fletcher (captured via Claude conversation)
**Date:** 2026-04-10
**Audience:** Future NBNE decision-makers, Beacon (when it starts making recommendations), anyone touching the Google Ads account
**Status:** Living document — update as new lessons emerge
**Related:** `BEACON_PHASE_1_CC_PROMPT.md`, `PHLOE_BEACON_MODULE_SPEC.md`

---

## Purpose

This document captures what NBNE has learned from running Google Ads historically, so that future campaigns (whether human-managed or Beacon-managed) don't repeat expensive mistakes. It is deliberately specific to NBNE's context — generic "Google Ads best practice" advice is not the goal. The goal is to remember what happened *here*, with *this* business, and why.

---

## Historical context

### The 2021-ish Shopify era

Around 2021-2022, NBNE ran Google Ads to drive traffic to a Shopify site selling personalised memorial products. Toby managed the account himself with no prior Google Ads experience, pre-dating the availability of capable AI assistants for ad-hoc learning.

**The numbers, approximately:**
- Monthly spend: ~£600
- Monthly revenue attributable to ads: ~£600
- Duration: several months before the account was wound down
- Net result: the account lost money when gross margin was accounted for

**What went wrong at the mechanical level (known or strongly suspected):**
- Conversion tracking was not correctly configured. Tag setup, conversion actions, and attribution were probably all wrong to varying degrees.
- Smart bidding (if enabled) was optimising against incomplete or misattributed signals.
- Keyword match types, negative keywords, and search term review were not managed at any level of rigour.
- No systematic review of what the ads were actually showing on, what the landing pages looked like, or whether the audience matched the product.
- No AI assistance was available at the time, so problem diagnosis was slow and largely self-taught.

**What went wrong at the strategic level (clearer in hindsight):**
- The product category (personalised memorials) had a gross margin per unit that could not sustain the customer acquisition cost Google Ads required. A £15-£25 CPA on a £20-£40 order with ~50% gross margin means every sale lost money before fulfilment costs were even counted.
- This was a gross-margin problem dressed up as a Google Ads problem. The account was finding real buyers with real intent at a real conversion rate — the machinery worked. The economics didn't.

---

## Core lessons

### Lesson 1 — Google Ads amplifies unit economics; it doesn't create them

If your gross margin per customer can't support a £10-£30 CPA, Google Ads will lose you money no matter how well the campaigns are set up. This is the single most important lesson from the Shopify era. Before spending a pound on ads for any product or service, run this calculation:

```
Max affordable CPA = (Average order value) × (Gross margin %) × (Target payback ratio)
```

Where the target payback ratio reflects how much of the gross margin you're willing to spend on acquisition. For a healthy account, this is usually 20-50% (i.e. spend 20-50% of gross margin on acquisition, keep the rest as net contribution). For a repeat-purchase or recurring-revenue product, the calculation can use LTV instead of first-order value.

**Products where this is favourable at NBNE:**
- B2B commercial signage: £500-£10,000 ticket × 30-50% margin × 30% payback = £50-£1,500 affordable CPA. Very comfortable room for advertising.
- Phloe SaaS: £25-£50/month × 12-month LTV estimate × 30% payback = £90-£180 affordable CAC. Workable but tight, and competition from funded players makes it hard in practice.

**Products where this is unfavourable at NBNE:**
- Personalised memorial products (£20-£60 orders with thin margin after fulfilment, packaging, returns). Do not advertise these on Google Ads.
- Generic FBA products where the margin is already eaten by Amazon fees. Do not advertise these on Google Ads either — if they needed advertising they'd be advertised on Amazon, not sent traffic from a colder source.
- Anything where the actual net contribution per sale is under £10. The arithmetic doesn't work at any CPC.

### Lesson 2 — Know what a "good conversion" is before you spend anything

Google Ads smart bidding optimises for whatever you tell it is a conversion. If you tell it "any form submission," it will find the cheapest form submissions, which will be the lowest-intent, lowest-value visitors. If you tell it "quote request for a job over £1,000," it will try to find those — but only if the conversion data actually reflects that distinction.

Before starting any new campaign, write down explicitly:
- What a "good lead" looks like (specific: e.g. "B2B enquiry with a real company name and a site address")
- What a "bad lead" looks like (specific: e.g. "residential request for a single house number")
- How the conversion tracking will distinguish between them (either by form fields, lead qualification, or by feeding won-deal data back via offline conversion upload — this is what Beacon is being built to do)

Without this, you will pay for leads Google thinks are wins that you think are waste. This is the mechanical origin of most "Google Ads is a scam" stories.

### Lesson 3 — One working conversion action beats twenty-three broken ones

At 2026-04-10 the current Google Ads account (202-863-1064) has 23 conversion actions of which only 4 are recording conversions. The rest are historical experiments that were never cleaned up. This is not an unusual state — it happens to every Google Ads account that's been running for more than a year without active maintenance.

Lessons:
- When starting a new campaign or new account, create *one* conversion action for the primary goal. Add more only when there's a specific reason to measure something the primary action doesn't cover.
- When retiring an experiment, archive the conversion action, don't leave it "paused" — archived actions don't clutter the summary view and can't accidentally fire later.
- Review the conversions summary quarterly. Anything with "Tag inactive," "Unverified," or "No recent conversions" for over 30 days should be investigated or archived.
- Never rely on Google's default "imported from GA4" conversion actions without verifying them — they import regardless of whether they're configured correctly on the GA4 side.

### Lesson 4 — Auto-apply recommendations are a trap

Google Ads displays an "optimisation score" and recommends changes to push it toward 100%. Many of these recommendations are net-harmful:
- "Add broad match variants" — balloons spend on irrelevant queries
- "Add search partners" — lower-quality traffic from the broader Google network
- "Enable Display expansion" — puts search ads on unrelated display placements
- "Convert exact/phrase match to broad match" — destroys targeting precision
- "Increase your budget" — always the recommendation when your impression share is under 100%, regardless of whether more spend actually helps

**Default stance: auto-apply is off.** Review recommendations manually, and treat them as suggestions to be evaluated, not decisions to be rubber-stamped. An 80-90% optimisation score is healthy; 100% usually means capitulation to Google's suggestions rather than a well-run account.

### Lesson 5 — Relationship channels and growth channels are different things, and you need both

Jo Fletcher's Facebook and networking activity generates NBNE's highest-quality B2B leads. These are relationship channels: high trust, high conversion, low unit cost, entirely dependent on Jo's time and attention being available.

Google Ads is a growth channel: lower trust, lower conversion, dial-up-and-down with spend, independent of any single person's time.

**A business running only on relationship channels is single-threaded.** When the relationship person is unavailable for any reason (production spike, holiday, illness, life events), enquiries drop and there is no backup catching the gap. This is exactly what happened to NBNE in March-April 2026: a spike in personalised Amazon orders consumed Jo's attention, her social posting and networking reduced, and B2B signage enquiries dropped within weeks. The Google Ads account contributed nothing meaningful to catching that gap because it was running £3/day on memorial keywords.

**The lesson is not "Google Ads is the answer."** The lesson is: a healthy B2B business needs both a relationship channel *and* a growth channel running in parallel, so that when one is constrained, the other provides continuity. Google Ads is a reasonable candidate for the growth channel for NBNE's B2B signage work — but only if it's actually set up to target that business.

### Lesson 6 — Trust your gut on "Google Ads is a black box"

Toby's stated instinct is a dislike of Google Ads combined with an acknowledgement that it's probably a good fit for B2B signage and Phloe. Both halves of this are correct:

- The dislike is rational. Google Ads is genuinely opaque, optimised to extract maximum spend from advertisers, actively hostile to manual control (via "recommendations" that undermine careful setup), and filled with conversion-rate-destroying defaults.
- The fit is also real. For high-ticket B2B lead gen in a niche with low competition and clear intent keywords, Google Ads is genuinely one of the best channels available.

**The resolution to this tension is control — specifically, automated control that Beacon is being designed to provide.** Beacon's closed-loop attribution (click → booking → paid job → ROAS per campaign) is precisely the feedback mechanism that would have caught the £600-in / £600-out failure in 2021 within the first week instead of running for months. Beacon is the form of Google Ads use that resolves the "dislike vs fit" tension: the channel is used where it genuinely fits, and it is constrained by automation that catches failure modes early.

Do not run Google Ads at NBNE without either (a) a human with active attention spent on weekly review, or (b) Beacon or an equivalent automated system catching problems. Passive management is how the 2021 losses happened.

---

## Specific things to avoid next time

Not all lessons fit into numbered categories. These are miscellaneous mistakes from the historical account that are specifically worth avoiding:

- **Naming campaigns vaguely.** "Shop Signage in Northumberland" sounds like retail shop fascias, but is arguably trying to serve all B2B signage. Names should be precise: "B2B Commercial Signage — Northumberland — Search — Exact" tells you what it is at a glance.
- **Letting paused campaigns accumulate.** Paused doesn't mean gone — the settings, disapproved ads, and conversion history all stay around adding noise to audits. Archive or delete retired campaigns properly.
- **Advertising products that are being phased out.** Spending money to drive traffic to products you're trying to discontinue (e.g. the memorial line) is negative-value — you pay to acquire customers you don't want.
- **Running campaigns without a reviewed landing page.** The landing page is half the conversion rate. A Google Ads campaign pointing at a generic homepage will always underperform a campaign pointing at a dedicated, intent-matched landing page.
- **Ignoring search terms reports.** The single highest-value weekly activity on any Google Ads account is reviewing the actual search terms the ads showed on and adding irrelevant ones as negatives. Five minutes a week saves more money than any other action.
- **Treating Google Ads as a set-and-forget channel.** It isn't. Every Google Ads account drifts without active attention — keyword match expansion, new broad-match variants being automatically added, recommendations auto-applying, landing page changes breaking tracking. This is the failure mode that created the current state of account 202-863-1064.

---

## The forward strategy (summary)

Decided in this conversation, to be executed when the right sequencing allows:

1. **Leave the current Google Ads account (202-863-1064) as a sandbox.** Do not repurpose, clean up, or rebuild. Turn off auto-apply if it's on. The £3/day spend is apparently generating some real B2B website enquiries as a side effect — leave it running until a new account is ready.
2. **Create a new dedicated Google Ads account for B2B commercial signage.** Under MCC 214-126-2231 as a sub-account. Clean start. Timing: aligned with Beacon Phase 1 readiness, but earlier if the enquiries situation demands it.
3. **Do not create a Phloe Google Ads account yet.** Phloe is not operationally mature enough to justify it, and competition from funded players makes it a harder channel. Revisit in 3-6 months.
4. **Before spending anything on the new B2B signage account:** build a proper B2B signage landing page hero'ing the CEng / BS 7910 engineering differentiator, set up *one* working conversion action (form submission, tracked end-to-end), and write down explicitly what a "good lead" looks like for smart bidding to learn from.
5. **Start with £300-£500/month on the new B2B signage account** for the first three months. Enough to generate meaningful data without betting the business. Scale up if mechanics are working.
6. **Hold off on significant Google Ads work until Beacon Phase 1 is ready.** Beacon is the destination, not the starting point. Manual Google Ads management is for the interim only.
7. **Accept that Jo's relationship channels are the highest-quality source of B2B leads but are not scalable.** Google Ads is additive growth capacity, not a replacement.

---

## Open questions for Beacon to answer when it has data

Things we can't currently answer but will want Beacon to address once it's running:

- What's the actual cost per B2B signage lead on the current £3/day account? The 2 conversions shown on Shop Signage are of unknown quality.
- Which specific search terms are driving the B2B enquiries that are coming through? Without good tag coverage historically, this has been invisible.
- What's the realistic win rate on B2B signage quote requests sourced from Google Ads vs Jo's relationship channels? Intuition says relationship leads convert far better, but we have no numbers.
- Does the engineering differentiator actually convert in ad copy, or is it more effective on the landing page and CTAs? Needs A/B testing at a later stage.
- What's the saturation point on B2B signage spend in Northumberland specifically? At some budget level, geographic and audience limits will start to bite.

---

## Document maintenance

This document should be updated:
- When new lessons emerge from live campaigns
- When Beacon begins reporting real data that confirms or contradicts these lessons
- When NBNE's product mix shifts significantly (e.g. memorial phase-out complete, new product lines added)
- At least annually as a deliberate review

Do not delete content from this document — if a lesson turns out to be wrong, add a follow-up noting the correction rather than deleting the original. The history of what was believed and when is part of the value.
