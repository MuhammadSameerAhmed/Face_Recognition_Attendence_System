from flask import Flask, render_template_string, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
import pandas as pd
import io
import base64


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///face_attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Database model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reg_no = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    dob = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    attendance_count = db.Column(db.Integer, default=0)
    leaves_taken = db.Column(db.Integer, default=0)
    last_leave_month = db.Column(db.String(7), nullable=True)  # YYYY-MM
    messages = db.Column(db.Text, nullable=True)
    face_image = db.Column(db.Text, nullable=True)  # Base64 image data

    def age(self):
        today = date.today()
        return today.year - self.dob.year - ((today.month, today.day) < (self.dob.month, self.dob.day))

# Initialize DB (create tables)
with app.app_context():
    db.create_all()

# Helper functions
def generate_next_reg_no():
    year = datetime.now().year
    code = 'XYZ'
    users = User.query.filter(User.reg_no.like(f"{year}-{code}-%")).all()
    max_suffix = 0
    for u in users:
        try:
            suffix = int(u.reg_no.split('-')[2])
            if suffix > max_suffix:
                max_suffix = suffix
        except:
            continue
    next_suffix = max_suffix + 1
    return f"{year}-{code}-{str(next_suffix).zfill(4)}"

def generate_email(name):
    if not name:
        return ''
    normalized = name.strip().lower()
    import unicodedata, re
    normalized = unicodedata.normalize('NFD', normalized)
    normalized = normalized.encode('ascii', 'ignore').decode('utf-8')
    normalized = re.sub(r'[^a-z\s]', '', normalized)
    parts = normalized.split()
    if len(parts) == 0:
        return ''
    if len(parts) == 1:
        base_email = f"{parts[0]}@company.com"
    else:
        base_email = f"{parts[0]}.{parts[-1]}@company.com"

    # Check for existing emails and append number if needed
    existing_emails = {u.email.lower() for u in User.query.all()}
    email_candidate = base_email
    counter = 1
    while email_candidate.lower() in existing_emails:
        if len(parts) == 1:
            email_candidate = f"{parts[0]}{counter}@company.com"
        else:
            email_candidate = f"{parts[0]}.{parts[-1]}{counter}@company.com"
        counter += 1
    return email_candidate

def get_working_days_in_month(year, month):
    count = 0
    from calendar import monthrange
    days_in_month = monthrange(year, month)[1]
    for day in range(1, days_in_month + 1):
        weekday = date(year, month, day).weekday()
        if weekday < 5:  # Monday=0, Sunday=6
            count += 1
    return count

# Routes
@app.route('/')
def index():
    return render_template_string(TEMPLATE_HTML)

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    name = data.get('name', '').strip()
    dob_str = data.get('dob', '').strip()
    gender = data.get('gender', '').strip()
    face_image = data.get('face_image', '').strip()

    if not (name and dob_str and gender and face_image):
        return jsonify({'error': 'Missing required fields'}), 400

    # Check duplicate name (case insensitive)
    if User.query.filter(db.func.lower(User.name) == name.lower()).first():
        return jsonify({'error': f'User with name "{name}" already registered.'}), 400

    try:
        dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
    except Exception:
        return jsonify({'error': 'Invalid date of birth format.'}), 400

    email = generate_email(name)

    # Double check email uniqueness (should be handled by generate_email, but just in case)
    if User.query.filter(db.func.lower(User.email) == email.lower()).first():
        return jsonify({'error': f'Email "{email}" already registered.'}), 400

    reg_no = generate_next_reg_no()

    user = User(
        reg_no=reg_no,
        name=name,
        dob=dob,
        gender=gender,
        email=email,
        attendance_count=0,
        leaves_taken=0,
        last_leave_month=None,
        messages='',
        face_image=face_image
    )
    db.session.add(user)
    db.session.commit()

    return jsonify({'success': True, 'reg_no': reg_no, 'email': email, 'name': name})

@app.route('/recognize', methods=['POST'])
def recognize():
    import random
    data = request.json
    users = User.query.all()
    if not users:
        return jsonify({'recognized': False, 'message': 'No users registered yet.'})
    if random.random() < 0.5:
        user = random.choice(users)
        user.attendance_count += 1
        db.session.commit()
        return jsonify({
            'recognized': True,
            'reg_no': user.reg_no,
            'name': user.name,
            'attendance_count': user.attendance_count,
            'message': f'Recognized {user.name} ({user.reg_no}). Attendance incremented.'
        })
    else:
        return jsonify({'recognized': False, 'message': 'Face not recognized. Please register.'})

@app.route('/admin/users', methods=['GET'])
def admin_users():
    users = User.query.all()
    users_list = []
    for u in users:
        users_list.append({
            'reg_no': u.reg_no,
            'name': u.name,
            'age': u.age(),
            'gender': u.gender,
            'email': u.email,
            'attendance_count': u.attendance_count
        })
    return jsonify(users_list)

@app.route('/admin/user/<reg_no>', methods=['GET', 'DELETE'])
def admin_user(reg_no):
    user = User.query.filter_by(reg_no=reg_no).first()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    if request.method == 'GET':
        return jsonify({
            'reg_no': user.reg_no,
            'name': user.name,
            'age': user.age(),
            'gender': user.gender,
            'email': user.email,
            'attendance_count': user.attendance_count
        })
    elif request.method == 'DELETE':
        db.session.delete(user)
        db.session.commit()
        return jsonify({'success': True, 'message': f'User {reg_no} deleted.'})

@app.route('/export', methods=['GET'])
def export_excel():
    users = User.query.all()
    if not users:
        return jsonify({'error': 'No user data to export.'}), 400
    df = pd.DataFrame([{
        'RegNo': u.reg_no,
        'Name': u.name,
        'Age': u.age(),
        'Gender': u.gender,
        'Email': u.email,
        'Attendance Count': u.attendance_count,
        'Date of Birth': u.dob.strftime('%Y-%m-%d'),
        'Leaves Taken': u.leaves_taken,
        'Messages': u.messages or ''
    } for u in users])
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Users')
    output.seek(0)
    return send_file(output, download_name="FaceAttendanceUsers.xlsx", as_attachment=True)

@app.route('/status', methods=['POST'])
def check_status():
    data = request.json
    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify({'error': 'Please enter an email address.'}), 400
    user = User.query.filter(db.func.lower(User.email) == email).first()
    if not user:
        return jsonify({'error': 'No user found with this email.'}), 404

    now = datetime.now()
    year = now.year
    month = now.month
    working_days = get_working_days_in_month(year, month)

    current_month_str = f"{year}-{month}"
    if user.last_leave_month != current_month_str:
        user.leaves_taken = 0
        user.last_leave_month = current_month_str
        db.session.commit()

    attendance_count = user.attendance_count
    leaves_taken = user.leaves_taken

    attendance_percent = 100.0
    if working_days > 0:
        attendance_percent = max(0, ((working_days - leaves_taken) / working_days) * 100)

    messages = []
    if leaves_taken > 2:
        messages.append(f"Alert: You have taken more than 2 leaves ({leaves_taken}) this month.")
    if attendance_percent < 90:
        messages.append(f"Warning: Your attendance is below 90% ({attendance_percent:.1f}%).")
    if attendance_percent == 100:
        messages.append("Great job! You have 100% attendance this month.")
    if not messages:
        messages.append("Your attendance and leave status are within acceptable limits.")

    user.messages = ' | '.join(messages)
    db.session.commit()

    return jsonify({
        'name': user.name,
        'attendance_count': attendance_count,
        'leaves_taken': leaves_taken,
        'attendance_percent': round(attendance_percent, 1),
        'messages': messages
    })

# HTML Template with embedded JS and Tailwind CSS CDN
TEMPLATE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1" name="viewport"/>
<title>Face Attendance System - Flask Version</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.3/css/all.min.css" rel="stylesheet"/>
<style>
  body { font-family: 'Inter', sans-serif; }
  #user-list { max-height: 300px; overflow-y: auto; }
  #user-list table { width: 100%; border-collapse: collapse; }
  #user-list th, #user-list td { border: 1px solid rgba(255,255,255,0.3); padding: 8px; text-align: center; }
  #user-list th { background-color: rgba(255,255,255,0.1); }
  #user-list::-webkit-scrollbar { width: 6px; }
  #user-list::-webkit-scrollbar-thumb { background-color: rgba(255,255,255,0.3); border-radius: 3px; }
  #registration-modal > div { max-height: 90vh; overflow-y: auto; }
</style>
</head>
<body class="bg-gradient-to-r from-indigo-600 via-purple-700 to-pink-600 min-h-screen flex flex-col">
<header class="bg-white bg-opacity-20 backdrop-blur-md shadow-md sticky top-0 z-50">
 <nav class="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between flex-wrap">
  <div class="flex items-center space-x-3 flex-shrink-0">
   <img alt="Face Attendance System logo" class="rounded-full" height="40" src="https://storage.googleapis.com/a1aa/image/6f676429-b5ca-4973-54fd-653030150ec1.jpg" width="40"/>
   <h1 class="text-white text-2xl font-bold tracking-wide select-none">Face Attendance System</h1>
  </div>
  <ul class="hidden md:flex space-x-8 text-white font-semibold flex-grow justify-center">
   <li><button class="hover:text-yellow-300 transition focus:outline-none" id="nav-home-btn" type="button">Home</button></li>
   <li><button class="hover:text-yellow-300 transition focus:outline-none" id="nav-face-rec-btn" type="button">Face Recognition</button></li>
   <li><button class="hover:text-yellow-300 transition focus:outline-none" id="nav-admin-btn" type="button">Admin Tools</button></li>
   <li><button class="hover:text-yellow-300 transition focus:outline-none" id="export-excel-btn" type="button" title="Export all user data to Excel"><i class="fas fa-file-excel"></i> Export Excel</button></li>
  </ul>
  <button aria-label="Toggle menu" class="md:hidden text-white focus:outline-none" id="mobile-menu-button"><i class="fas fa-bars fa-lg"></i></button>
 </nav>
 <div class="hidden md:hidden bg-white bg-opacity-20 backdrop-blur-md px-6 py-4 space-y-4 text-white font-semibold" id="mobile-menu">
  <button class="block w-full text-left hover:text-yellow-300 transition focus:outline-none" id="mobile-nav-home-btn" type="button">Home</button>
  <button class="block w-full text-left hover:text-yellow-300 transition focus:outline-none" id="mobile-nav-face-rec-btn" type="button">Face Recognition</button>
  <button class="block w-full text-left hover:text-yellow-300 transition focus:outline-none" id="mobile-nav-admin-btn" type="button">Admin Tools</button>
  <button class="block w-full text-left hover:text-yellow-300 transition focus:outline-none" id="mobile-export-excel-btn" type="button" title="Export all user data to Excel"><i class="fas fa-file-excel"></i> Export Excel</button>
 </div>
</header>
<main class="flex-grow max-w-7xl mx-auto px-6 py-12 space-y-20 text-white min-h-[calc(100vh-112px)] flex flex-col justify-center">
 <!-- Home Section -->
 <section class="max-w-4xl mx-auto flex flex-col items-center text-center" id="section-home">
  <h2 class="text-4xl md:text-5xl font-extrabold mb-4 drop-shadow-lg">Welcome to the Face Attendance System</h2>
  <p class="text-lg md:text-xl max-w-3xl leading-relaxed drop-shadow-md">A modern, secure, and easy-to-use face recognition attendance system. Use face recognition to mark attendance or register new users when not recognized.</p>
  <img alt="Face scan illustration" class="mt-8 rounded-lg shadow-lg border-4 border-white border-opacity-30 max-w-full h-auto" height="300" src="https://storage.googleapis.com/a1aa/image/03d94911-0696-4fca-0207-2989de3ee2eb.jpg" width="600"/>
 </section>
 <!-- Face Recognition Section -->
 <section class="hidden max-w-4xl mx-auto bg-white bg-opacity-20 backdrop-blur-md rounded-xl p-8 shadow-lg flex flex-col items-center" id="section-face-rec">
  <h3 class="text-3xl font-bold mb-6 text-yellow-400 text-center">Face Recognition Attendance</h3>
  <p class="text-white mb-6 max-w-xl">Webcam will open and try to recognize your face. If recognized, attendance count will increment automatically. If not recognized, you can register by capturing your face and entering your details.</p>
  <div class="flex flex-col sm:flex-row justify-center space-y-4 sm:space-y-0 sm:space-x-4 mb-4 w-full max-w-md">
   <button class="bg-yellow-400 hover:bg-yellow-500 text-black font-bold py-3 px-6 rounded-md shadow-md transition w-full" id="start-face-rec-btn" type="button">Start Face Recognition</button>
   <button class="bg-green-500 hover:bg-green-600 text-white font-bold py-3 px-6 rounded-md shadow-md hidden w-full" id="register-new-user-btn" type="button">Register New User</button>
  </div>
  <p class="mt-4 font-semibold text-white text-center min-h-[2rem]" id="face-rec-message"></p>
  <div class="mt-6 flex justify-center w-full max-w-lg">
   <video autoplay class="rounded-lg shadow-lg border-4 border-white border-opacity-30 w-full h-auto max-h-[360px]" id="video" playsinline style="display:none;"></video>
  </div>
  <div class="mt-8 max-w-md w-full bg-white bg-opacity-20 rounded-lg p-4 text-white">
   <label for="email-check" class="block font-semibold mb-2">Enter Email to Check Attendance & Leave Status</label>
   <input id="email-check" type="email" placeholder="Enter user email" class="w-full rounded-md px-3 py-2 text-black" />
   <button id="check-attendance-btn" class="mt-3 bg-yellow-400 hover:bg-yellow-500 text-black font-bold py-2 px-4 rounded-md shadow-md w-full transition">Check Status</button>
   <div id="attendance-status" class="mt-4 text-center font-semibold"></div>
  </div>
 </section>
 <!-- Registration Modal -->
 <div class="fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center z-60 hidden" id="registration-modal" role="dialog" aria-modal="true" aria-labelledby="registration-title">
  <div class="bg-white rounded-xl max-w-md w-full p-8 relative max-h-[90vh] overflow-y-auto flex flex-col">
   <h3 class="text-2xl font-bold mb-6 text-gray-900 text-center" id="registration-title">Register New User</h3>
   <form class="space-y-6 text-gray-900 flex flex-col" id="register-form" style="min-height: 600px;">
    <div>
     <label class="block mb-1 font-semibold" for="name">Full Name</label>
     <input class="w-full rounded-md px-3 py-2 border border-gray-300 focus:outline-yellow-400 focus:ring-2 focus:ring-yellow-400" id="name" name="name" placeholder="Enter full name" required type="text"/>
    </div>
    <div>
     <label class="block mb-1 font-semibold" for="dob">Date of Birth</label>
     <input class="w-full rounded-md px-3 py-2 border border-gray-300 focus:outline-yellow-400 focus:ring-2 focus:ring-yellow-400" id="dob" max="" name="dob" required type="date"/>
    </div>
    <div>
     <label class="block mb-1 font-semibold" for="gender">Gender</label>
     <select class="w-full rounded-md px-3 py-2 border border-gray-300 focus:outline-yellow-400 focus:ring-2 focus:ring-yellow-400" id="gender" name="gender" required>
      <option disabled selected value="">Select gender</option>
      <option>Male</option>
      <option>Female</option>
      <option>Other</option>
      <option>Prefer not to say</option>
     </select>
    </div>
    <div>
     <label class="block mb-1 font-semibold" for="email">Generated Email</label>
     <input class="w-full rounded-md px-3 py-2 bg-yellow-100 text-black cursor-not-allowed" id="email" name="email" placeholder="Email will be generated automatically" readonly type="email"/>
    </div>
    <div>
     <label class="block mb-1 font-semibold" for="face-capture">Face Capture</label>
     <canvas class="w-full rounded-md border border-gray-300" height="240" id="face-canvas" width="320"></canvas>
     <p class="mt-1 text-sm text-gray-600">Click on the video below to capture your face image.</p>
     <video autoplay class="rounded-lg shadow-lg border-4 border-gray-300 mt-2 max-w-full cursor-pointer mx-auto block" id="reg-video" playsinline width="320" height="240" style="display:block;"></video>
     <p class="mt-2 text-red-600 font-semibold text-center" id="capture-warning" style="display:none;">Please capture your face by clicking on the video.</p>
    </div>
    <div class="flex flex-col sm:flex-row justify-between items-center mt-6 space-y-4 sm:space-y-0 sm:space-x-4">
     <button class="bg-gray-400 hover:bg-gray-500 text-white font-bold py-2 px-6 rounded-md shadow-md transition w-full sm:w-auto" id="cancel-registration-btn" type="button">Cancel</button>
     <button class="bg-yellow-400 hover:bg-yellow-500 text-black font-bold py-2 px-6 rounded-md shadow-md transition w-full sm:w-auto" id="submit-registration-btn" type="submit" disabled>Submit Registration</button>
    </div>
    <p class="mt-4 text-center font-semibold text-red-600" id="registration-error"></p>
    <p class="mt-4 text-center font-semibold text-green-600" id="registration-success"></p>
   </form>
  </div>
 </div>
 <!-- Admin Tools Page -->
 <div class="fixed inset-0 bg-indigo-900 bg-opacity-95 backdrop-blur-md z-50 overflow-auto hidden" id="admin-page">
  <div class="max-w-5xl mx-auto p-8 text-white min-h-[calc(100vh-64px)] flex flex-col">
   <div class="flex justify-between items-center mb-8">
    <h2 class="text-4xl font-extrabold text-yellow-400">Admin Tools</h2>
    <button aria-label="Close Admin Tools" class="text-yellow-400 hover:text-yellow-300 focus:outline-none" id="admin-close-btn" type="button"><i class="fas fa-times fa-2x"></i></button>
   </div>
   <div class="grid grid-cols-1 md:grid-cols-3 gap-8 mb-6">
    <div class="bg-indigo-700 bg-opacity-40 rounded-lg p-6 shadow-md hover:bg-indigo-800 transition cursor-pointer flex flex-col items-center text-center" id="admin-search-user">
     <i class="fas fa-search fa-3x mb-4 text-yellow-400"></i>
     <h4 class="text-xl font-semibold mb-2">Search User by RegNo</h4>
     <p>Find user details quickly by entering their registration number.</p>
    </div>
    <div class="bg-indigo-700 bg-opacity-40 rounded-lg p-6 shadow-md hover:bg-indigo-800 transition cursor-pointer flex flex-col items-center text-center" id="admin-view-users">
     <i class="fas fa-users fa-3x mb-4 text-yellow-400"></i>
     <h4 class="text-xl font-semibold mb-2">View All Users</h4>
     <p>Browse all registered users in a convenient table view.</p>
    </div>
    <div class="bg-indigo-700 bg-opacity-40 rounded-lg p-6 shadow-md hover:bg-indigo-800 transition cursor-pointer flex flex-col items-center text-center" id="admin-delete-user">
     <i class="fas fa-user-times fa-3x mb-4 text-yellow-400"></i>
     <h4 class="text-xl font-semibold mb-2">Delete User by RegNo</h4>
     <p>Remove a user and all their data by entering their registration number.</p>
    </div>
   </div>
   <p class="text-center font-semibold text-yellow-400 mb-6 flex-grow" id="admin-message"></p>
   <div class="overflow-auto" id="user-list" style="display:none; max-height: 50vh;">
    <h3 class="text-2xl font-bold mb-4 text-yellow-400 text-center">Registered Users</h3>
    <table class="min-w-full table-auto border-collapse border border-yellow-400 text-white">
     <thead>
      <tr>
       <th class="border border-yellow-400 px-3 py-2">RegNo</th>
       <th class="border border-yellow-400 px-3 py-2">Name</th>
       <th class="border border-yellow-400 px-3 py-2">Age</th>
       <th class="border border-yellow-400 px-3 py-2">Gender</th>
       <th class="border border-yellow-400 px-3 py-2">Email</th>
       <th class="border border-yellow-400 px-3 py-2">Attendance Count</th>
      </tr>
     </thead>
     <tbody id="user-list-body"></tbody>
    </table>
   </div>
  </div>
 </div>
<footer class="bg-white bg-opacity-20 backdrop-blur-md text-white text-center py-6 mt-auto shadow-inner">
 <p>© 2024 Face Attendance System. All rights reserved.</p>
</footer>
<script>
  // Mobile menu toggle
  const menuBtn = document.getElementById('mobile-menu-button');
  const mobileMenu = document.getElementById('mobile-menu');
  menuBtn.addEventListener('click', () => {
    mobileMenu.classList.toggle('hidden');
  });

  // Navigation buttons
  const sectionHome = document.getElementById('section-home');
  const sectionFaceRec = document.getElementById('section-face-rec');
  const adminPage = document.getElementById('admin-page');

  function showSection(section) {
    sectionHome.classList.add('hidden');
    sectionFaceRec.classList.add('hidden');
    adminPage.classList.add('hidden');
    section.classList.remove('hidden');
    clearMessages();
    if (section !== sectionFaceRec) stopVideoStream();
    if (section !== adminPage) hideUserList();
    clearEmailCheck();
  }

  function clearMessages() {
    document.getElementById('face-rec-message').textContent = '';
    document.getElementById('admin-message').textContent = '';
    clearRegistrationMessages();
  }
  function clearRegistrationMessages() {
    document.getElementById('registration-error').textContent = '';
    document.getElementById('registration-success').textContent = '';
  }
  function clearEmailCheck() {
    document.getElementById('email-check').value = '';
    document.getElementById('attendance-status').textContent = '';
  }

  // Desktop nav buttons
  document.getElementById('nav-home-btn').addEventListener('click', () => showSection(sectionHome));
  document.getElementById('nav-face-rec-btn').addEventListener('click', () => showSection(sectionFaceRec));
  document.getElementById('nav-admin-btn').addEventListener('click', () => {
    adminPage.classList.remove('hidden');
    clearMessages();
    stopVideoStream();
    hideUserList();
    clearEmailCheck();
  });

  // Mobile nav buttons
  document.getElementById('mobile-nav-home-btn').addEventListener('click', () => {
    showSection(sectionHome);
    mobileMenu.classList.add('hidden');
  });
  document.getElementById('mobile-nav-face-rec-btn').addEventListener('click', () => {
    showSection(sectionFaceRec);
    mobileMenu.classList.add('hidden');
  });
  document.getElementById('mobile-nav-admin-btn').addEventListener('click', () => {
    adminPage.classList.remove('hidden');
    clearMessages();
    stopVideoStream();
    hideUserList();
    mobileMenu.classList.add('hidden');
    clearEmailCheck();
  });

  // Export Excel buttons
  document.getElementById('export-excel-btn').addEventListener('click', () => {
    window.location.href = '/export';
  });
  document.getElementById('mobile-export-excel-btn').addEventListener('click', () => {
    window.location.href = '/export';
    mobileMenu.classList.add('hidden');
  });

  // Close admin page
  document.getElementById('admin-close-btn').addEventListener('click', () => {
    adminPage.classList.add('hidden');
    hideUserList();
    clearEmailCheck();
  });

  // Face Recognition Section Elements
  const startFaceRecBtn = document.getElementById('start-face-rec-btn');
  const registerNewUserBtn = document.getElementById('register-new-user-btn');
  const faceRecMessage = document.getElementById('face-rec-message');
  const video = document.getElementById('video');
  let stream = null;
  let recognizedUser = null;

  async function startWebcam() {
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: true });
      video.srcObject = stream;
      video.style.display = 'block';
      faceRecMessage.textContent = 'Webcam started. Recognizing face... (Simulation)';
      recognizedUser = null;
      registerNewUserBtn.classList.add('hidden');

      // Capture image from webcam after 3 seconds and send to backend for recognition
      setTimeout(async () => {
        const canvas = document.createElement('canvas');
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const imgData = canvas.toDataURL('image/png');

        // Call backend recognize API
        const res = await fetch('/recognize', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ face_image: imgData })
        });
        const data = await res.json();
        if(data.recognized){
          faceRecMessage.textContent = data.message;
          registerNewUserBtn.classList.add('hidden');
        } else {
          faceRecMessage.textContent = data.message;
          registerNewUserBtn.classList.remove('hidden');
        }
      }, 3000);

    } catch (err) {
      faceRecMessage.textContent = 'Error accessing webcam: ' + err.message;
      faceRecMessage.className = 'mt-4 text-center font-semibold text-red-400';
    }
  }

  function stopVideoStream() {
    if (stream) {
      stream.getTracks().forEach(track => track.stop());
      stream = null;
    }
    video.style.display = 'none';
    faceRecMessage.textContent = '';
    registerNewUserBtn.classList.add('hidden');
  }

  startFaceRecBtn.addEventListener('click', () => {
    faceRecMessage.className = 'mt-4 text-center font-semibold text-yellow-300';
    startWebcam();
  });

  registerNewUserBtn.addEventListener('click', () => {
    openRegistrationModal();
  });

  // Registration Modal Elements
  const registrationModal = document.getElementById('registration-modal');
  const regVideo = document.getElementById('reg-video');
  const faceCanvas = document.getElementById('face-canvas');
  const ctx = faceCanvas.getContext('2d');
  const captureWarning = document.getElementById('capture-warning');
  const submitRegistrationBtn = document.getElementById('submit-registration-btn');
  const cancelRegistrationBtn = document.getElementById('cancel-registration-btn');
  const registrationError = document.getElementById('registration-error');
  const registrationSuccess = document.getElementById('registration-success');
  const regNameInput = document.getElementById('name');
  const regDobInput = document.getElementById('dob');
  const regGenderInput = document.getElementById('gender');
  const regEmailInput = document.getElementById('email');
  const regForm = document.getElementById('register-form');

  let regStream = null;
  let faceCapturedImageData = null;

  function openRegistrationModal() {
    registrationModal.classList.remove('hidden');
    registrationError.textContent = '';
    registrationSuccess.textContent = '';
    submitRegistrationBtn.disabled = true;
    captureWarning.style.display = 'none';
    regForm.reset();
    regEmailInput.value = '';
    startRegWebcam();
  }

  function closeRegistrationModal() {
    registrationModal.classList.add('hidden');
    stopRegVideoStream();
  }

  cancelRegistrationBtn.addEventListener('click', () => {
    closeRegistrationModal();
  });

  async function startRegWebcam() {
    try {
      regStream = await navigator.mediaDevices.getUserMedia({ video: true });
      regVideo.srcObject = regStream;
      regVideo.style.display = 'block';
      faceCapturedImageData = null;
      submitRegistrationBtn.disabled = true;
      captureWarning.style.display = 'none';
    } catch (err) {
      registrationError.textContent = 'Error accessing webcam: ' + err.message;
    }
  }

  function stopRegVideoStream() {
    if (regStream) {
      regStream.getTracks().forEach(track => track.stop());
      regStream = null;
    }
    regVideo.style.display = 'none';
  }

  regVideo.addEventListener('click', () => {
    if (!regStream) return;
    ctx.drawImage(regVideo, 0, 0, faceCanvas.width, faceCanvas.height);
    faceCapturedImageData = faceCanvas.toDataURL('image/png');
    captureWarning.style.display = 'none';
    submitRegistrationBtn.disabled = false;
    registrationError.textContent = '';
  });

  regNameInput.addEventListener('input', () => {
    const name = regNameInput.value.trim();
    if (!name) {
      regEmailInput.value = '';
      return;
    }
    // Generate email (simple version)
    const parts = name.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z\s]/g, '').split(/\s+/);
    if(parts.length === 1) regEmailInput.value = parts[0] + '@company.com';
    else if(parts.length > 1) regEmailInput.value = parts[0] + '.' + parts[parts.length - 1] + '@company.com';
    else regEmailInput.value = '';
    registrationError.textContent = '';
    registrationSuccess.textContent = '';
  });

  regDobInput.max = new Date().toISOString().split('T')[0];

  regForm.addEventListener('submit', async e => {
    e.preventDefault();
    registrationError.textContent = '';
    registrationSuccess.textContent = '';

    const name = regNameInput.value.trim();
    const dob = regDobInput.value;
    const gender = regGenderInput.value;
    const email = regEmailInput.value;

    if (!name || !dob || !gender) {
      registrationError.textContent = 'Please fill in all required fields.';
      return;
    }
    if (!faceCapturedImageData) {
      registrationError.textContent = 'Please capture your face by clicking on the video.';
      captureWarning.style.display = 'block';
      return;
    }

    // Send registration data to backend
    try {
      const res = await fetch('/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, dob, gender, face_image: faceCapturedImageData })
      });
      const data = await res.json();
      if (data.error) {
        registrationError.textContent = data.error;
      } else if (data.success) {
        registrationSuccess.textContent = `User registered successfully: ${data.name} (${data.reg_no})`;
        submitRegistrationBtn.disabled = true;
        setTimeout(() => {
          closeRegistrationModal();
        }, 4000);
      }
    } catch (err) {
      registrationError.textContent = 'Error registering user: ' + err.message;
    }
  });

  // Admin tools
  const adminSearchUserBtn = document.getElementById('admin-search-user');
  const adminViewUsersBtn = document.getElementById('admin-view-users');
  const adminDeleteUserBtn = document.getElementById('admin-delete-user');
  const adminMessage = document.getElementById('admin-message');
  const userListDiv = document.getElementById('user-list');
  const userListBody = document.getElementById('user-list-body');

  adminSearchUserBtn.addEventListener('click', async () => {
    const regNo = prompt('Enter Registration Number to search:');
    if (!regNo) {
      adminMessage.textContent = 'Search cancelled.';
      adminMessage.className = 'mt-6 text-center font-semibold text-red-400';
      return;
    }
    try {
      const res = await fetch('/admin/user/' + regNo);
      if(res.status === 404){
        adminMessage.textContent = `No user found with RegNo: ${regNo.toUpperCase()}`;
        adminMessage.className = 'mt-6 text-center font-semibold text-red-400';
        return;
      }
      const user = await res.json();
      adminMessage.textContent = `User found: ${user.name} (RegNo: ${user.reg_no}), Age: ${user.age}, Gender: ${user.gender}, Email: ${user.email}, Attendance Count: ${user.attendance_count}`;
      adminMessage.className = 'mt-6 text-center font-semibold text-green-400';
      hideUserList();
    } catch (err) {
      adminMessage.textContent = 'Error searching user: ' + err.message;
      adminMessage.className = 'mt-6 text-center font-semibold text-red-400';
    }
  });

  adminViewUsersBtn.addEventListener('click', async () => {
    try {
      const res = await fetch('/admin/users');
      const users = await res.json();
      if(users.length === 0){
        adminMessage.textContent = 'No registered users found.';
        adminMessage.className = 'mt-6 text-center font-semibold text-red-400';
        hideUserList();
        return;
      }
      adminMessage.textContent = '';
      showUserList(users);
    } catch(err) {
      adminMessage.textContent = 'Error loading users: ' + err.message;
      adminMessage.className = 'mt-6 text-center font-semibold text-red-400';
    }
  });

  adminDeleteUserBtn.addEventListener('click', async () => {
    const regNo = prompt('Enter Registration Number to delete:');
    if (!regNo) {
      adminMessage.textContent = 'Delete cancelled.';
      adminMessage.className = 'mt-6 text-center font-semibold text-red-400';
      return;
    }
    const confirmDelete = confirm(`Are you sure you want to delete user with RegNo: ${regNo.toUpperCase()}?`);
    if (!confirmDelete) {
      adminMessage.textContent = 'Delete cancelled.';
      adminMessage.className = 'mt-6 text-center font-semibold text-red-400';
      return;
    }
    try {
      const res = await fetch('/admin/user/' + regNo, { method: 'DELETE' });
      const data = await res.json();
      if(data.success){
        adminMessage.textContent = data.message;
        adminMessage.className = 'mt-6 text-center font-semibold text-green-400';
        hideUserList();
      } else {
        adminMessage.textContent = data.error || 'Delete failed.';
        adminMessage.className = 'mt-6 text-center font-semibold text-red-400';
      }
    } catch(err) {
      adminMessage.textContent = 'Error deleting user: ' + err.message;
      adminMessage.className = 'mt-6 text-center font-semibold text-red-400';
    }
  });

  function showUserList(users) {
    userListBody.innerHTML = '';
    users.forEach(user => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="border border-yellow-400 px-3 py-2">${user.reg_no}</td>
        <td class="border border-yellow-400 px-3 py-2">${user.name}</td>
        <td class="border border-yellow-400 px-3 py-2">${user.age}</td>
        <td class="border border-yellow-400 px-3 py-2">${user.gender}</td>
        <td class="border border-yellow-400 px-3 py-2">${user.email}</td>
        <td class="border border-yellow-400 px-3 py-2">${user.attendance_count}</td>
      `;
      userListBody.appendChild(tr);
    });
    userListDiv.style.display = 'block';
  }
  function hideUserList() {
    userListDiv.style.display = 'none';
    userListBody.innerHTML = '';
  }

  // Check attendance and leave status by email
  const emailCheckInput = document.getElementById('email-check');
  const checkAttendanceBtn = document.getElementById('check-attendance-btn');
  const attendanceStatusDiv = document.getElementById('attendance-status');

  checkAttendanceBtn.addEventListener('click', async () => {
    const email = emailCheckInput.value.trim();
    attendanceStatusDiv.textContent = '';
    if (!email) {
      attendanceStatusDiv.textContent = 'Please enter an email address.';
      attendanceStatusDiv.className = 'mt-4 text-center font-semibold text-red-500';
      return;
    }
    try {
      const res = await fetch('/status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });
      const data = await res.json();
      if(data.error){
        attendanceStatusDiv.textContent = data.error;
        attendanceStatusDiv.className = 'mt-4 text-center font-semibold text-red-500';
        return;
      }
      attendanceStatusDiv.innerHTML = `
        <p><strong>Name:</strong> ${data.name}</p>
        <p><strong>Attendance Count:</strong> ${data.attendance_count}</p>
        <p><strong>Leaves Taken This Month:</strong> ${data.leaves_taken}</p>
        <p><strong>Attendance %:</strong> ${data.attendance_percent}%</p>
        <div class="mt-2 space-y-1">${data.messages.map(m => `<p>${m}</p>`).join('')}</div>
      `;
      attendanceStatusDiv.className = 'mt-4 text-center font-semibold text-yellow-300';
    } catch (err) {
      attendanceStatusDiv.textContent = 'Error checking status: ' + err.message;
      attendanceStatusDiv.className = 'mt-4 text-center font-semibold text-red-500';
    }
  });

</script>
</body>
</html>
"""

if __name__ == '__main__':
    app.run(debug=True)
