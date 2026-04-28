import os
import uuid
import shutil
import zipfile
from flask import Flask, request, render_template_string, redirect, url_for, send_from_directory, jsonify, session
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import pytz

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key-change-this'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hosting.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB per site

# Create directories
os.makedirs('hosted_sites', exist_ok=True)
os.makedirs('uploads', exist_ok=True)

db = SQLAlchemy(app)

# Database Models
class HostedSite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    site_name = db.Column(db.String(100), unique=True, nullable=False)
    subdomain = db.Column(db.String(100), unique=True, nullable=False)
    owner_name = db.Column(db.String(100), nullable=False)
    owner_email = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(200), default='My Static Site')
    description = db.Column(db.Text, default='')
    folder_path = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(pytz.UTC))
    views = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    password_protected = db.Column(db.Boolean, default=False)
    site_password = db.Column(db.String(200), nullable=True)

class SiteFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('hosted_site.id'))
    filename = db.Column(db.String(200), nullable=False)
    file_path = db.Column(db.String(200), nullable=False)
    upload_date = db.Column(db.DateTime, default=lambda: datetime.now(pytz.UTC))

with app.app_context():
    db.create_all()

# Read HTML templates
def get_html(template_name):
    with open(template_name, 'r', encoding='utf-8') as f:
        return f.read()

# Main routes
@app.route('/')
def index():
    sites = HostedSite.query.filter_by(is_active=True).order_by(HostedSite.created_at.desc()).all()
    total_sites = HostedSite.query.count()
    total_views = db.session.query(db.func.sum(HostedSite.views)).scalar() or 0
    
    html = get_html('index.html')
    return render_template_string(html, sites=sites, total_sites=total_sites, total_views=total_views)

@app.route('/create-site', methods=['POST'])
def create_site():
    site_name = request.form.get('site_name')
    subdomain = request.form.get('subdomain')
    owner_name = request.form.get('owner_name')
    owner_email = request.form.get('owner_email')
    
    # Clean subdomain
    subdomain = secure_filename(subdomain.lower().replace(' ', ''))
    
    # Check if subdomain exists
    if HostedSite.query.filter_by(subdomain=subdomain).first():
        return "Subdomain already taken! Choose another.", 400
    
    # Create folder for the site
    folder_path = os.path.join('hosted_sites', subdomain)
    os.makedirs(folder_path, exist_ok=True)
    
    # Create default index.html
    default_html = f'''<!DOCTYPE html>
<html>
<head>
    <title>{site_name}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: Arial, sans-serif;
            text-align: center;
            padding: 50px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
        }}
        h1 {{ font-size: 48px; margin-bottom: 20px; }}
        .status {{
            background: rgba(255,255,255,0.2);
            padding: 20px;
            border-radius: 10px;
            margin-top: 30px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>✨ {site_name}</h1>
        <p>Welcome to my website hosted on NEXUS Hosting Platform!</p>
        <div class="status">
            <p>📁 This site was created on {datetime.now().strftime('%Y-%m-%d')}</p>
            <p>🔄 Upload your files through the NEXUS dashboard</p>
        </div>
    </div>
</body>
</html>'''
    
    with open(os.path.join(folder_path, 'index.html'), 'w') as f:
        f.write(default_html)
    
    # Save to database
    new_site = HostedSite(
        site_name=site_name,
        subdomain=subdomain,
        owner_name=owner_name,
        owner_email=owner_email,
        folder_path=folder_path
    )
    db.session.add(new_site)
    db.session.commit()
    
    return redirect(url_for('site_dashboard', site_id=new_site.id))

@app.route('/dashboard/<int:site_id>')
def site_dashboard(site_id):
    site = HostedSite.query.get_or_404(site_id)
    files = SiteFile.query.filter_by(site_id=site_id).all()
    html = get_html('dashboard.html')
    return render_template_string(html, site=site, files=files)

@app.route('/upload-file/<int:site_id>', methods=['POST'])
def upload_file(site_id):
    site = HostedSite.query.get_or_404(site_id)
    
    if 'file' not in request.files:
        return "No file", 400
    
    file = request.files['file']
    if file.filename == '':
        return "No file selected", 400
    
    filename = secure_filename(file.filename)
    file_path = os.path.join(site.folder_path, filename)
    file.save(file_path)
    
    site_file = SiteFile(
        site_id=site_id,
        filename=filename,
        file_path=file_path
    )
    db.session.add(site_file)
    db.session.commit()
    
    return redirect(url_for('site_dashboard', site_id=site_id))

@app.route('/upload-zip/<int:site_id>', methods=['POST'])
def upload_zip(site_id):
    site = HostedSite.query.get_or_404(site_id)
    
    if 'zipfile' not in request.files:
        return "No file", 400
    
    zip_file = request.files['zipfile']
    if zip_file.filename == '':
        return "No file selected", 400
    
    # Save zip temporarily
    temp_zip = os.path.join('uploads', f"{uuid.uuid4().hex}.zip")
    zip_file.save(temp_zip)
    
    # Extract zip
    with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
        zip_ref.extractall(site.folder_path)
    
    # Clean up
    os.remove(temp_zip)
    
    return redirect(url_for('site_dashboard', site_id=site_id))

@app.route('/delete-file/<int:site_id>/<int:file_id>')
def delete_file(site_id, file_id):
    site_file = SiteFile.query.get_or_404(file_id)
    if os.path.exists(site_file.file_path):
        os.remove(site_file.file_path)
    db.session.delete(site_file)
    db.session.commit()
    return redirect(url_for('site_dashboard', site_id=site_id))

@app.route('/delete-site/<int:site_id>')
def delete_site(site_id):
    site = HostedSite.query.get_or_404(site_id)
    # Delete folder
    shutil.rmtree(site.folder_path)
    # Delete files from DB
    SiteFile.query.filter_by(site_id=site_id).delete()
    db.session.delete(site)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/site/<subdomain>')
def view_site(subdomain):
    site = HostedSite.query.filter_by(subdomain=subdomain, is_active=True).first_or_404()
    site.views += 1
    db.session.commit()
    
    # Serve static files from the site's folder
    return send_from_directory(site.folder_path, 'index.html')

@app.route('/site/<subdomain>/<path:filename>')
def view_site_file(subdomain, filename):
    site = HostedSite.query.filter_by(subdomain=subdomain, is_active=True).first_or_404()
    return send_from_directory(site.folder_path, filename)

@app.route('/api/sites')
def api_sites():
    sites = HostedSite.query.filter_by(is_active=True).all()
    return jsonify([{
        'name': s.site_name,
        'subdomain': s.subdomain,
        'url': f"/site/{s.subdomain}",
        'views': s.views,
        'created': s.created_at.isoformat()
    } for s in sites])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)