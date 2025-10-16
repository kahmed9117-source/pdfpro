from flask import Flask, render_template, request, send_file, redirect, url_for, jsonify, session
from PyPDF2 import PdfMerger
import os
import stripe

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'

# --- SECRET KEYS ---
# Stripe Secret Key from environment
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")

# Flask session secret key (for storing user plan)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "some-random-secret")

# --- Home Page ---
@app.route('/')
def home():
    # Initialize user plan in session
    if 'user_plan' not in session:
        session['user_plan'] = 'free'
    return render_template('index.html', plan=session['user_plan'])


# --- Upload & Merge PDF ---
@app.route('/merge', methods=['POST'])
def merge_pdfs():
    files = request.files.getlist('pdfs')

    # Limit for Free users
    if session.get('user_plan') == 'free' and len(files) > 3:
        return "<h3>Free users can merge max 3 PDFs. Upgrade to Premium!</h3>"

    merger = PdfMerger()
    output_path = os.path.join(app.config['UPLOAD_FOLDER'], 'merged.pdf')

    for f in files:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f.filename)
        f.save(filepath)
        merger.append(filepath)

    merger.write(output_path)
    merger.close()
    return send_file(output_path, as_attachment=True)


# --- Stripe Checkout ---
@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    session_stripe = stripe.checkout.Session.create(
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


# --- Payment Success / Cancel ---
@app.route('/success')
def success():
    # Upgrade user plan to premium after successful payment
    session['user_plan'] = 'premium'
    return "<h1>Payment Successful ✅ You are now Premium!</h1>"


@app.route('/cancel')
def cancel():
    return "<h1>Payment Cancelled ❌</h1>"


# --- Run App ---
if __name__ == "__main__":
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True)
