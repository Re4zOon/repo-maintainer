# Screenshots and Visual Examples

This document provides visual examples of the email notifications and how they appear.

## Email Notification Example

You can view a live example of the email notification by opening [email-example.html](email-example.html) in your web browser.

### Preview

The email notification features:

1. **Eye-catching header** with gradient background and emojis
2. **Friendly greeting** to make the notification less intimidating
3. **Clear organization** separating merge requests and branches
4. **Visual badges** showing count of items
5. **Actionable guidance** with clear next steps
6. **Friendly warning** about cleanup timeline
7. **Professional footer** with helpful tips

### Email Subject Lines

Depending on the content, recipients will see one of these subjects:

- **Both MRs and Branches**: `[Action Required] 5 Stale Item(s) Require Attention`
- **Only MRs**: `[Action Required] 3 Stale Merge Request(s) Require Attention`
- **Only Branches**: `[Action Required] 2 Stale Branch(es) Require Attention`

### Color Scheme

The email uses GitLab's brand colors and friendly accents:

- **Header**: Orange gradient (#fc6d26 to #fca326)
- **Merge Requests**: Green background (#d4edda) for positive actions
- **Branches**: Light gray background (#f8f9fa) for neutral items
- **Actions**: Blue accent (#e7f3ff) for guidance
- **Warning**: Red accent (#f8d7da) for urgency

### Mobile Responsive

The email template is mobile-friendly and looks good on:
- Desktop email clients (Outlook, Thunderbird, etc.)
- Webmail (Gmail, Yahoo, Outlook.com)
- Mobile devices (iOS Mail, Android Gmail, etc.)

## How to Test the Email Locally

1. Open `docs/email-example.html` in your web browser:
   ```bash
   cd docs
   open email-example.html  # macOS
   # or
   xdg-open email-example.html  # Linux
   # or just double-click the file in your file explorer
   ```

2. The example shows:
   - 2 stale merge requests
   - 1 stale branch
   - All sections of the email template

3. You can edit this file to customize the template and see how changes look

## Customization Examples

### Changing the Header Color

Edit the CSS in `stale_branch_notifier.py`:

```css
.header { 
    background: linear-gradient(135deg, #your-color-1, #your-color-2);
}
```

Popular gradients:
- **Blue**: `#667eea` to `#764ba2`
- **Green**: `#56ab2f` to `#a8e063`
- **Purple**: `#6a11cb` to `#2575fc`
- **Red/Orange**: `#fc6d26` to `#fca326` (current)

### Adding Company Logo

Add this to the header section in the template:

```html
<div class="header">
    <img src="https://your-company.com/logo.png" 
         alt="Company Logo" 
         style="max-width: 150px; margin-bottom: 15px;">
    <h1>Time for Some Spring Cleaning! ✨</h1>
</div>
```

### Changing the Tone

**More Formal:**
```html
<div class="greeting">
    <p>Dear Team Member,</p>
</div>
```

**More Casual:**
```html
<div class="greeting">
    <p>Hey there, Code Ninja! 🥷</p>
</div>
```

## Accessibility Features

The email template includes:

- ✅ **Semantic HTML** for screen readers
- ✅ **High contrast** colors for readability
- ✅ **Clear headings** hierarchy
- ✅ **Descriptive link text** (not "click here")
- ✅ **Emoji with text** (not emoji-only content)

## Email Client Compatibility

Tested and working on:

| Email Client | Status | Notes |
|--------------|--------|-------|
| Gmail Web | ✅ Excellent | Full CSS support |
| Outlook 2016+ | ✅ Good | Basic gradients supported |
| Apple Mail | ✅ Excellent | Full CSS support |
| Thunderbird | ✅ Excellent | Full CSS support |
| Yahoo Mail | ✅ Good | Most features work |
| Outlook.com | ✅ Good | Basic CSS support |
| Mobile Gmail | ✅ Excellent | Responsive layout |
| iOS Mail | ✅ Excellent | Full CSS support |

**Note**: Some corporate email clients may strip CSS or images. The email is designed to still be readable with basic HTML only.

## Spam Filter Considerations

The email template is designed to avoid spam filters by:

- ✅ Using proper HTML structure
- ✅ Including both HTML and text content
- ✅ Avoiding spam trigger words
- ✅ Using legitimate from address
- ✅ Including unsubscribe information (add if needed)
- ✅ Balanced image-to-text ratio (emoji are text)

## See Also

- [Email Notifications Guide](EMAIL_NOTIFICATIONS.md) - Detailed email system documentation
- [Configuration Reference](CONFIGURATION.md) - Customize email settings
- [Setup Guide](SETUP_GUIDE.md) - SMTP configuration
