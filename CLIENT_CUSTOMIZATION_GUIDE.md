# 🎨 Client Customization Guide

## Quick Reference for Common Customizations

### 1. 🎨 Changing Colors

#### Primary Brand Color
**File:** `static/css/theme.css` (Line 27)
```css
--accent-blue: #3b82f6;  /* Change this hex code to your brand color */
```

**Also in:** `templates/dashboard.html` (Lines 154-175)
- Blue cards use: `#3b82f6`
- Orange cards use: `#f97316`
- Pink cards use: `#ec4899`
- Green cards use: `#10b981`
- Purple cards use: `#8b5cf6`
- Teal cards use: `#14b8a6`

#### How to Change:
1. Open the file
2. Find the hex code (e.g., `#3b82f6`)
3. Replace with your desired color (e.g., `#0066cc`)
4. Save and refresh the browser

#### Color Picker Tool:
Use any online color picker to get hex codes:
- https://htmlcolorcodes.com/
- https://www.color-hex.com/

---

### 2. 🖼️ Adding Images

#### Login Page Logo
**File:** `templates/login.html` (Line 181)
```html
<!-- Replace this image: Add your company logo here (recommended size: 100x100px) -->
```

**How to add:**
1. Save your logo as `logo.png` in the `static/` folder
2. Replace the emoji with: `<img src="{{ url_for('static', filename='logo.png') }}" alt="Logo" style="width: 100px; height: 100px;">`

#### Dashboard Header Image
**File:** `templates/dashboard.html` (Line 115)
```html
<!-- Replace this image: Add dashboard header image here (recommended size: 1200x300px) -->
```

#### Other Pages:
- Booth page: `templates/booth.html` (Line 68)
- Location page: `templates/location.html` (Line 68)
- Analytics page: `templates/analytics.html` (Line 68)

---

### 3. 👥 Managing Users

**File:** `login.csv`

Add new users:
```csv
username,password,role,client_name
admin,admin123,admin,
newuser,password123,client,clientA
```

**Roles:**
- `admin` - Full access to all data
- `client` - Only sees their own client's data

---

### 4. 🏢 Managing Clients & Booths

**File:** `clients.csv`

Add new locations and booths:
```csv
client_name,location,booth,booth_id,max_occupancy
clientA,Adelaide,Booth A,ADEL-001,4
clientA,Adelaide,Booth B,ADEL-002,2
clientB,Melbourne,Booth A,MELB-001,2
```

---

### 5. 🔄 Auto-Refresh Interval

**File:** `static/js/custom.js` (Line 89)

Change refresh interval:
```javascript
startAutoRefresh(60000); // 60 seconds
```

**Common intervals:**
- 30000 = 30 seconds
- 60000 = 1 minute
- 120000 = 2 minutes
- 300000 = 5 minutes

---

### 6. 🔐 Security - Change Secret Key

**File:** `app.py` (Line 50)

**IMPORTANT:** Change this for production!

```python
app.secret_key = 'your_very_secret_key'
```

Generate a secure key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

### 7. 📊 Google Sheets Configuration

**File:** `app.py` (Line 95)

Change the spreadsheet name:
```python
spreadsheet = gspread_client.open("Simulated_Sensor_Data")
```

Replace `"Simulated_Sensor_Data"` with your Google Sheet name.

**Worksheet naming convention:**
Each worksheet should be named: `location_booth`
- Example: `Adelaide_Booth A`
- Example: `Melbourne_Booth B`

---

### 8. 📝 Application Title

**Files to update:**
- `templates/login.html` (Line 182): `<h1>🏢 Bureau Booths</h1>`
- `templates/dashboard.html` (Line 76): `<h1 class="heading-h2">📊 Bureau Booths Dashboard</h1>`
- `templates/booth.html` (Line 29): `<h1 class="heading-h2">🏢 Bureau Booths</h1>`
- `templates/location.html` (Line 29): `<h1 class="heading-h2">📍 Bureau Booths</h1>`

Replace "Bureau Booths" with your application name.

---

### 9. 🎯 Customization Checklist

- [ ] Change secret key in `app.py`
- [ ] Update user credentials in `login.csv`
- [ ] Update client/booth data in `clients.csv`
- [ ] Configure Google Sheets connection
- [ ] Add company logo to `static/` folder
- [ ] Update application title in templates
- [ ] Customize brand colors in `theme.css`
- [ ] Add header images to pages
- [ ] Set auto-refresh interval
- [ ] Test all functionality
- [ ] Deploy to production

---

### 10. 🚀 Deployment

See `README.md` for:
- Installation instructions
- Running the application
- Production deployment with Gunicorn
- Environment variables setup

---

## 📞 Common Issues

**Q: Colors not changing?**
A: Clear browser cache (Ctrl+Shift+Delete) and refresh

**Q: Images not showing?**
A: Check file path and ensure image is in `static/` folder

**Q: Google Sheets not connecting?**
A: Verify `newcred.json` exists and credentials are valid

**Q: Users can't login?**
A: Check `login.csv` format and ensure no extra spaces

---

**Last Updated:** October 2025

