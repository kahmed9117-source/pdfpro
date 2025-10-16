import os
from flask import Flask, render_template, request, send_file, redirect, url_for, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
import stripe
import boto3
from io import BytesIO
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from werkzeug.utils import secure_filename

# --------------------
# Flask Setup
# --------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Stripe
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
endpoint_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

# AWS S3
s3 = boto3.client(
    "s3",
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    region_name=os.environ.get("AWS_REGION")
)
S3_BUCKET = os.environ.get("S3_BUCKET_NAME")

# --------------------
# Models
# --------------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    plan = db.Column(db.String(20), default='free')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --------------------
# Routes
# --------------------
@app.route('/')
def home():
    plan = current_user.plan if current_user.is_authenticated else 'free'
    return render_template('index.html', plan=plan)

# --------------------
# Auth
# --------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email=email)
            db.session.add(user)
            db.session.commit()
        login_user(user)
        return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('home'))

# --------------------
# PDF Tools
# --------------------
def upload_to_s3(file_bytes, filename):
    s3.put_object(Bucket=S3_BUCKET, Key=filename, Body=file_bytes, ContentType='application/pdf')
    return f"https://{S3_BUCKET}.s3.amazonaws.com/{filename}"

@app.route('/merge', methods=['POST'])
@login_required
def merge_pdfs():
    files = request.files.getlist('pdfs')
    if current_user.plan == 'free' and len(files) > 3:
        return "<h3>Free users can merge a max of 3 PDFs. Upgrade to Premium!</h3>"

    merger = PdfMerger()
    for f in files:
        merger.append(f)
    output = BytesIO()
    merger.write(output)
    merger.close()
    output.seek(0)

    filename = "merged.pdf"
    url = upload_to_s3(output.getvalue(), filename)
    return jsonify({"file_url": url})

@app.route('/split', methods=['POST'])
@login_required
def split_pdf():
    file = request.files['pdf']
    reader = PdfReader(file)
    urls = []
    for i in range(len(reader.pages)):
        writer = PdfWriter()
        writer.add_page(reader.pages[i])
        output = BytesIO()
        writer.write(output)
        output.seek(0)
        filename = f"page_{i+1}.pdf"
        urls.append(upload_to_s3(output.getvalue(), filename))
    return jsonify({"split_files": urls})

@app.route('/compress', methods=['POST'])
@login_required
def compress_pdf():
    # Placeholder for real compression (use Ghostscript or pikepdf for real optimization)
    file = request.files['pdf']
    filename = secure_filename(file.filename)
    upload_to_s3(file.read(), filename)
    return jsonify({"compressed_file": f"https://{S3_BUCKET}.s3.amazonaws.com/{filename}"})

# --------------------
# Stripe Checkout
# --------------------
@app.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    session_stripe = stripe.checkout.Session.create(
        customer_email=current_user.email,
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'product_data': {'name': 'Premium PDF Tools'},
                'unit_amount': 500,  # $5.00
            },
            'quantity': 1,
        }],
        mode='payment',
        success_url=url_for('success', _external=True),
        cancel_url=url_for('cancel', _external=True),
    )
    return jsonify({'url': session_stripe.url})

@app.route('/success')
@login_required
def success():
    current_user.plan = 'premium'
    db.session.commit()
    return "<h1>Payment Successful ✅ You are now Premium!</h1>"

@app.route('/cancel')
def cancel():
    return "<h1>Payment Cancelled ❌</h1>"

# --------------------
# Webhook for Stripe (auto upgrade)
# --------------------
@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    event = None
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except stripe.error.SignatureVerificationError:
        return "Invalid signature", 400

    if event['type'] == 'checkout.session.completed':
        email = event['data']['object']['customer_email']
        user = User.query.filter_by(email=email).first()
        if user:
            user.plan = 'premium'
            db.session.commit()

    return "Success", 200

# --------------------
# Run
# --------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
