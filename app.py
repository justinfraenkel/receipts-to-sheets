from flask import Flask, render_template, request, send_file, flash, redirect
import os
from io import BytesIO, StringIO
import csv
import base64
import openai
from dotenv import load_dotenv
import re
from werkzeug.utils import secure_filename

# Config
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
UPLOAD_FOLDER = 'uploads'
LOG_FILE = 'logs.csv'
MAX_FILE_SIZE_MB = 2  # 🔹 Reduced from 5MB to 2MB

app = Flask(__name__)
app.secret_key = "supersecretkey"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE_MB * 1024 * 1024  # 2MB max

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    files = request.files.getlist('receipt')

    if not files or files[0].filename == '':
        flash("No receipt file uploaded.")
        return redirect('/')

    if len(files) > 1:
        flash("Please upload only one receipt at a time for testing.")
        return redirect('/')

    file = files[0]
    filename = secure_filename(file.filename)

    if not file.mimetype.startswith('image/') and not filename.lower().endswith('.pdf'):
        flash(f"{filename} is not an image or PDF.")
        return redirect('/')

    headers = ['Date', 'Vendor', 'VAT Number', 'VAT', 'Total']
    rows = []

    try:
        image_bytes = file.read()
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        mime_type = file.mimetype

        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "From this receipt image, extract:\n"
                                "- Date (e.g. 2024-01-01)\n"
                                "- Vendor name\n"
                                "- VAT Number (even if not labeled, e.g., 10-digit SA number)\n"
                                "- VAT amount\n"
                                "- Total amount\n\n"
                                "Format like:\n"
                                "Date: 2024-01-01\nVendor: ABC Store\nVAT Number: 4900258591\nVAT: 72.55\nTotal: 557.20\n\n"
                                "Use 'Pending' if VAT Number is incomplete. Use 'Null' if a value is missing."
                            )
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}"
                            }
                        }
                    ]
                }
            ]
        )
        extracted_text = response.choices[0].message.content

    except Exception as e:
        flash(f"Failed to process {filename}. Error: {str(e)}")
        return redirect('/')

    data = {}
    for line in extracted_text.split("\n"):
        line = re.sub(r'^[-*]+\s*', '', line).replace("**", "").strip()
        if ":" in line:
            field, value = line.split(":", 1)
            data[field.strip()] = value.strip()

    def clean(val):
        v = val.strip()
        if not v:
            return "Null"
        if v.lower() == "null":
            return "Null"
        if v.lower() == "pending":
            return "Pending"
        return v

    row = [
        clean(data.get("Date", "")),
        clean(data.get("Vendor", "")),
        clean(data.get("VAT Number", "")),
        clean(data.get("VAT", "")),
        clean(data.get("Total", ""))
    ]
    rows.append(row)

    # Log to file
    with open(LOG_FILE, "a", newline='') as f:
        writer = csv.writer(f)
        if os.stat(LOG_FILE).st_size == 0:
            writer.writerow(headers)
        writer.writerow(row)

    # Return CSV download
    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    output = BytesIO(csv_buffer.getvalue().encode('utf-8'))
    output.seek(0)
    return send_file(output, mimetype='text/csv', as_attachment=True, download_name='receipts.csv')

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000, debug=True)
