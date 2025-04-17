from flask import Flask, request, render_template_string, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from datetime import datetime
import json
import os
import io
import csv

app = Flask(__name__)

# Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////home/Yankkk/mysite/mydatabase.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db = SQLAlchemy(app)

# ========== Data Models ==========
class Evaluation(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    # Judge
    judge_name = db.Column(db.String(100), nullable=True)
    judge_role = db.Column(db.String(50), nullable=False)  # ceo/intern1/intern2
    evaluation_date = db.Column(db.DateTime, default=datetime.utcnow)

    # Applicant
    applicant_name = db.Column(db.String(100), nullable=False)
    applicant_id = db.Column(db.String(50), nullable=False, index=True)
    applicant_role = db.Column(db.String(50), nullable=False)

    # Scores
    resume_score = db.Column(db.Float, nullable=False)  # 0~5
    resume_ratings = db.Column(db.Text, nullable=True)  # JSON string
    video_ratings = db.Column(db.Text, nullable=True)   # JSON string
    video_score = db.Column(db.Float, nullable=False)   # 0~5
    motivation_score = db.Column(db.Float, nullable=False, default=0.0)  # 0~5
    final_score = db.Column(db.Float, nullable=False)   # Final (0~5)

    # Decision & Notes
    decision = db.Column(db.String(50), nullable=False)
    notes = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

class Applicant(db.Model):
    __tablename__ = 'applicant_info'  # Use separate table name to avoid conflicts

    id = db.Column(db.Integer, primary_key=True)
    applicant_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), nullable=True)
    university = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    resume_url = db.Column(db.String(255), nullable=True)
    video_url = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(50), default='pending')  # pending, evaluated, advanced, waitlisted, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Initialize database
with app.app_context():
    # db.drop_all()  # Commented out to prevent data loss on restart
    db.create_all()

# ========== Helper Functions ==========
def get_video_criteria():
    """Return the structure of video evaluation criteria"""
    return [
        {
            "title": "Content Quality (25%)",
            "items": [
                {"id": "content_understanding", "label": "Understanding of Sertie Products and Value", "weight": 6.25},
                {"id": "content_clarity", "label": "Clarity of Viewpoint", "weight": 6.25},
                {"id": "content_problem_solving", "label": "Problem-Solving Approach", "weight": 6.25},
                {"id": "content_originality", "label": "Originality and Creativity", "weight": 6.25}
            ]
        },
        {
            "title": "Presentation Skills (25%)",
            "items": [
                {"id": "presentation_clarity", "label": "Communication Clarity", "weight": 8.33},
                {"id": "presentation_confidence", "label": "Confidence and Expressiveness", "weight": 8.33},
                {"id": "presentation_structure", "label": "Structure and Organization", "weight": 8.33}
            ]
        }
    ]

def get_resume_criteria(position):
    """Return position-based resume evaluation criteria"""
    base_criteria = [
        {"id": "resume_relevance", "label": "Relevant modules or work experiences", "weight": 10},
        {"id": "resume_extra", "label": "Additional work beyond studies or certifications", "weight": 10}
    ]

    if position == "financial-analyst":
        return [
            {"id": "resume_skills", "label": "Hard vs Soft Skills (70/30 split)", "weight": 15},
        ] + base_criteria
    elif position == "research-analyst":
        return [
            {"id": "resume_skills", "label": "Hard vs Soft Skills (40/60 split)", "weight": 15},
        ] + base_criteria
    elif position == "operations-analyst":
        return [
            {"id": "resume_skills", "label": "Hard vs Soft Skills (20/80 split)", "weight": 15},
        ] + base_criteria
    else:
        return [
            {"id": "resume_skills", "label": "Hard vs Soft Skills", "weight": 15},
        ] + base_criteria

def get_motivation_criteria():
    """Return the structure of motivation evaluation criteria"""
    return {
        "title": "Motivation (10%)",
        "items": [
            {"id": "motivation_enthusiasm", "label": "Enthusiasm for the Position", "weight": 10}
        ]
    }

def get_role_weight(role):
    """Return the weight factor for each judge role"""
    weights = {
        'ceo': 0.5,
        'intern1': 0.25,
        'intern2': 0.25
    }
    return weights.get(role, 0.25)

def get_position_name_english(position):
    """Return position name in English"""
    positions = {
        'financial-analyst': 'Financial Analyst',
        'research-analyst': 'Research Analyst',
        'operations-analyst': 'Operations Analyst'
    }
    return positions.get(position, position.replace('-', ' ').title())

def get_role_weights_for_export(position):
    """Return weight factors for each position"""
    if position == "financial-analyst":
        return {"hard": 0.7, "soft": 0.3}
    elif position == "research-analyst":
        return {"hard": 0.4, "soft": 0.6}
    elif position == "operations-analyst":
        return {"hard": 0.2, "soft": 0.8}
    else:
        return {"hard": 0.5, "soft": 0.5}  # Default to average weights

def format_float(value):
    """Format float value with consistent precision"""
    try:
        return f"{float(value):.1f}"
    except:
        return "0.0"

def escape_csv_field(value):
    """Properly escape a value for CSV inclusion"""
    if value is None:
        return '""'
    
    value = str(value)
    if ',' in value or '"' in value or '\n' in value or '\r' in value:
        # Escape quotes by doubling them and wrap in quotes
        return '"' + value.replace('"', '""') + '"'
    return value

def get_rating_score(ratings_dict, key):
    """Safely extract score from ratings dictionary"""
    if not ratings_dict:
        return ""

    # Try new format (data collected by frontend JS)
    item = ratings_dict.get(key, {})
    if isinstance(item, dict):
        return item.get('score', "")

    # Try old format (direct value)
    return ratings_dict.get(key, "")

# ========== Home Page ==========
@app.route('/')
def index():
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sertie Evaluation System</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
  <style>
    body {
      background-color: #B3FFFA;
      min-height: 100vh;
    }
    .container {
      padding-top: 30px;
      padding-bottom: 30px;
    }
    .card {
      transition: transform 0.3s, box-shadow 0.3s;
      border: none;
      border-radius: 10px;
      box-shadow: 0 4px 15px rgba(0,0,0,0.1);
      margin-bottom: 25px;
    }
    .card:hover {
      transform: translateY(-5px);
      box-shadow: 0 10px 25px rgba(0,0,0,0.15);
    }
    .card-header {
      border-radius: 10px 10px 0 0 !important;
      font-weight: bold;
    }
    .footer {
      text-align: center;
      padding: 20px;
      margin-top: 30px;
      color: #6c757d;
    }
    .stats-box {
      background: white;
      border-radius: 10px;
      padding: 15px;
      margin-bottom: 20px;
      box-shadow: 0 4px 10px rgba(0,0,0,0.05);
      text-align: center;
    }
    .stats-number {
      font-size: 2rem;
      font-weight: bold;
      color: #198754;
    }
    /* Mobile responsiveness improvements */
    @media (max-width: 768px) {
      .container {
        padding: 15px;
      }
      .stats-box {
        padding: 10px;
        margin-bottom: 15px;
      }
      .stats-number {
        font-size: 1.5rem;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <h1 class="text-center mb-4 text-success">Sertie x Spartech Ventures Challenge 2025</h1>
    <p class="text-center text-muted">Select your role to start evaluation, or view existing records.</p>

    <!-- Statistics Cards -->
    <div class="row mb-4">
      <div class="col-md-3 col-6">
        <div class="stats-box">
          <i class="bi bi-people-fill fs-2 text-primary"></i>
          <div class="stats-number">{{ applicant_count }}</div>
          <div>Applicants</div>
        </div>
      </div>
      <div class="col-md-3 col-6">
        <div class="stats-box">
          <i class="bi bi-clipboard-check-fill fs-2 text-success"></i>
          <div class="stats-number">{{ evaluation_count }}</div>
          <div>Evaluations</div>
        </div>
      </div>
      <div class="col-md-3 col-6">
        <div class="stats-box">
          <i class="bi bi-award-fill fs-2 text-warning"></i>
          <div class="stats-number">{{ acceptance_rate }}%</div>
          <div>Acceptance Rate</div>
        </div>
      </div>
      <div class="col-md-3 col-6">
        <div class="stats-box">
          <i class="bi bi-star-fill fs-2 text-danger"></i>
          <div class="stats-number">{{ avg_score }}</div>
          <div>Average Score</div>
        </div>
      </div>
    </div>

    <div class="row justify-content-center">
      <div class="col-md-4 mb-3">
        <div class="card">
          <div class="card-header bg-info text-white">
            <i class="bi bi-person-workspace"></i> CEO
          </div>
          <div class="card-body">
            <p class="card-text">Irene Veng (Weight: 50%)</p>
            <a href="/rating?role=ceo" class="btn btn-primary w-100">Start Evaluation</a>
          </div>
        </div>
      </div>
      <div class="col-md-4 mb-3">
        <div class="card">
          <div class="card-header bg-success text-white">
            <i class="bi bi-person"></i> Intern 1
          </div>
          <div class="card-body">
            <p class="card-text">Wei Wu (Weight: 25%)</p>
            <a href="/rating?role=intern1" class="btn btn-primary w-100">Start Evaluation</a>
          </div>
        </div>
      </div>
      <div class="col-md-4 mb-3">
        <div class="card">
          <div class="card-header bg-warning text-white">
            <i class="bi bi-person"></i> Intern 2
          </div>
          <div class="card-body">
            <p class="card-text">Yanwen Wang (Weight: 25%)</p>
            <a href="/rating?role=intern2" class="btn btn-primary w-100">Start Evaluation</a>
          </div>
        </div>
      </div>
    </div>

    <hr class="my-4">

    <div class="row">
      <div class="col-md-6 mb-3">
        <div class="card h-100">
          <div class="card-header bg-light">
            <i class="bi bi-list-ul"></i> View Saved Evaluations
          </div>
          <div class="card-body d-flex flex-column">
            <p>View all evaluation records</p>
            <a href="/evaluations" class="btn btn-outline-primary mt-auto w-100">Evaluation Records</a>
          </div>
        </div>
      </div>
      <div class="col-md-6 mb-3">
        <div class="card h-100">
          <div class="card-header bg-light">
            <i class="bi bi-bar-chart"></i> Combined Scores
          </div>
          <div class="card-body d-flex flex-column">
            <p>View applicants' combined evaluation scores</p>
            <a href="/combined-score" class="btn btn-outline-primary mt-auto w-100">Combined Scores</a>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div class="footer">
    <div class="container">
      <p>Sertie x Spartech Ventures Challenge 2025</p>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""
    # Calculate statistics
    applicant_count = db.session.query(func.count(db.distinct(Evaluation.applicant_id))).scalar()
    evaluation_count = Evaluation.query.count()
    avg_score = db.session.query(func.avg(Evaluation.final_score)).scalar() or 0

    # Calculate acceptance rate
    total_decisions = Evaluation.query.filter(Evaluation.decision.in_(['advance', 'waitlist', 'reject'])).count()
    advances = Evaluation.query.filter_by(decision='advance').count()
    acceptance_rate = 0 if total_decisions == 0 else round((advances / total_decisions) * 100)

    return render_template_string(html,
                                  applicant_count=applicant_count,
                                  evaluation_count=evaluation_count,
                                  avg_score=f"{avg_score:.1f}",
                                  acceptance_rate=acceptance_rate)

# ========== Rating Page ==========
@app.route('/rating')
def rating_page():
    # Get role
    judge_role = request.args.get('role', 'intern').lower()

    if judge_role == 'ceo':
        judge_name = "Irene Veng"
    elif judge_role == 'intern1':
        judge_name = "Wei Wu"
    else:
        judge_name = "Yanwen Wang"

    # Get applicant ID (if provided)
    applicant_id = request.args.get('applicant_id', '')
    applicant = None

    if applicant_id:
        try:
            applicant = Applicant.query.filter_by(applicant_id=applicant_id).first()
        except:
            # Ignore errors if Applicant table doesn't exist
            pass

    # Define hardcoded video evaluation criteria (avoiding potential function call issues)
    video_criteria_list = [
        {
            "title": "Content Quality (25%)",
            "items": [
                {"id": "content_understanding", "label": "Understanding of Sertie Products and Value", "weight": 6.25},
                {"id": "content_clarity", "label": "Clarity of Viewpoint", "weight": 6.25},
                {"id": "content_problem_solving", "label": "Problem-Solving Approach", "weight": 6.25},
                {"id": "content_originality", "label": "Originality and Creativity", "weight": 6.25}
            ]
        },
        {
            "title": "Presentation Skills (25%)",
            "items": [
                {"id": "presentation_clarity", "label": "Communication Clarity", "weight": 8.33},
                {"id": "presentation_confidence", "label": "Confidence and Expressiveness", "weight": 8.33},
                {"id": "presentation_structure", "label": "Structure and Organization", "weight": 8.33}
            ]
        }
    ]

    # HTML part of the template
    head_html = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Evaluation - {{ judge_role|capitalize }}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
  <style>
    body {
      background-color: #B3FFFA;
      font-family: Arial, sans-serif;
      margin: 0; padding: 0;
    }
    .container {
      max-width: 900px;
      margin: 30px auto;
      background-color: #fff;
      border-radius: 8px;
      box-shadow: 0 0 20px rgba(0,0,0,0.1);
      padding: 20px;
    }
    h1 {
      color: #009688;
      margin-bottom: 1rem;
    }
    .star-rating {
      display: inline-flex;
      font-size: 2rem;
      cursor: pointer;
    }
    .star-rating span {
      color: #ccc;
      margin: 0 4px;
      transition: color 0.2s;
    }
    .star-rating span.selected {
      color: #FFC107;
    }
    .criteria-section {
      margin-bottom: 20px;
      border: 1px solid #eee;
      border-radius: 8px;
      padding: 15px;
      background-color: #fdfdfd;
    }
    .criteria-title {
      font-weight: bold;
      background-color: #f5f5f5;
      padding: 10px;
      border-radius: 6px;
      margin-bottom: 15px;
    }
    .sub-criteria {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 15px;
      padding: 10px;
      border-bottom: 1px dashed #eee;
    }
    .sub-criteria:last-child {
      border-bottom: none;
    }
    .weight {
      font-size: 0.85rem;
      color: #666;
      margin-left: 5px;
      background-color: #f0f0f0;
      padding: 2px 6px;
      border-radius: 4px;
    }
    .form-section {
      background-color: #fff;
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 20px;
      box-shadow: 0 0 10px rgba(0,0,0,0.05);
    }
    .score-display {
      text-align: center;
      font-size: 1.2rem;
      margin: 15px 0;
      padding: 10px;
      background-color: #f8f9fa;
      border-radius: 8px;
    }
    .btn-group {
      display: flex;
      justify-content: space-between;
      margin-top: 30px;
    }
    .btn-group button {
      min-width: 120px;
      padding: 10px 20px;
    }
    .result-section {
      margin-top: 30px;
      border: 1px solid #dee2e6;
      border-radius: 8px;
      padding: 20px;
      background-color: #f8f9fa;
    }
    .final-score {
      font-size: 2.5rem;
      font-weight: bold;
      color: #009688;
      text-align: center;
      margin: 20px 0;
    }
    .progress {
      height: 8px;
      margin-bottom: 10px;
    }
    .nav-pills .nav-link.active {
      background-color: #009688;
    }
    /* Mobile responsiveness improvements */
    @media (max-width: 768px) {
      .container {
        padding: 10px;
        margin: 10px auto;
      }
      .sub-criteria {
        flex-direction: column;
        align-items: flex-start;
      }
      .star-rating {
        margin-top: 10px;
      }
      .btn-group {
        flex-direction: column;
      }
      .btn-group button {
        margin-bottom: 10px;
        width: 100%;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h1>
        <i class="bi bi-clipboard-check"></i>
        Sertie Evaluation - {{ judge_role|capitalize }}
      </h1>
      <a href="/" class="btn btn-outline-secondary">← Back to Home</a>
    </div>

    <!-- Progress Tracker -->
    <div class="mb-4">
      <ul class="nav nav-pills nav-fill mb-3" id="evaluationSteps" role="tablist">
        <li class="nav-item" role="presentation">
          <button class="nav-link active" id="step1-tab" data-bs-toggle="pill"
                  data-bs-target="#step1" type="button" role="tab">
              <i class="bi bi-info-circle"></i> Basic Information
          </button>
        </li>
        <li class="nav-item" role="presentation">
          <button class="nav-link" id="step2-tab" data-bs-toggle="pill"
                  data-bs-target="#step2" type="button" role="tab">
              <i class="bi bi-file-text"></i> Resume Evaluation
          </button>
        </li>
        <li class="nav-item" role="presentation">
          <button class="nav-link" id="step3-tab" data-bs-toggle="pill"
                  data-bs-target="#step3" type="button" role="tab">
              <i class="bi bi-camera-video"></i> Video Evaluation
          </button>
        </li>
        <li class="nav-item" role="presentation">
          <button class="nav-link" id="step4-tab" data-bs-toggle="pill"
                  data-bs-target="#step4" type="button" role="tab">
              <i class="bi bi-check-circle"></i> Final Decision
          </button>
        </li>
      </ul>
      <div class="progress">
        <div class="progress-bar bg-success" id="progressBar" role="progressbar" style="width: 25%"></div>
      </div>
    </div>

    <div class="tab-content" id="evaluationContent">
      <!-- Step 1: Basic Information -->
      <div class="tab-pane fade show active" id="step1" role="tabpanel">
        <div class="form-section">
          <h4><i class="bi bi-person-badge"></i> Evaluator Information</h4>
          <div class="row">
            <div class="col-md-4">
              <div class="mb-3">
                <label for="judge-name" class="form-label">Evaluator Name:</label>
                <input type="text" class="form-control" id="judge-name" value="{{ judge_name }}" readonly>
              </div>
            </div>
            <div class="col-md-4">
              <div class="mb-3">
                <label for="judge-role" class="form-label">Role:</label>
                <input type="text" class="form-control" id="judge-role" value="{{ judge_role }}" readonly>
              </div>
            </div>
            <div class="col-md-4">
              <div class="mb-3">
                <label for="evaluation-date" class="form-label">Evaluation Date:</label>
                <input type="date" class="form-control" id="evaluation-date">
              </div>
            </div>
          </div>
        </div>

        <div class="form-section">
          <h4><i class="bi bi-person"></i> Applicant Information</h4>
          <div class="row">
            <div class="col-md-4">
              <div class="mb-3">
                <label for="applicant-name" class="form-label">Applicant Name:</label>
                <input type="text" class="form-control" id="applicant-name"
                       placeholder="Enter name" value="{{ applicant.name if applicant else '' }}">
              </div>
            </div>
              <div class="col-md-6">
                <div class="mb-3">
                  <label for="applicant-university" class="form-label">University:</label>
                  <input type="text" class="form-control" id="applicant-university"
                         placeholder="Enter university" value="{{ applicant.university if applicant else '' }}">
                </div>
              </div>
              <div class="col-md-6">
                <div class="mb-3">
                  <label for="applicant-email" class="form-label">Email:</label>
                  <input type="email" class="form-control" id="applicant-email"
                         placeholder="Enter email" value="{{ applicant.email if applicant else '' }}">
                </div>
              </div>
             <div class="col-md-4">
               <div class="mb-3">
                 <label for="applicant-id" class="form-label">Applicant ID:</label>
                 <input type="text" class="form-control" id="applicant-id"
                        placeholder="Enter ID" value="{{ applicant.applicant_id if applicant else '' }}">
               </div>
              </div>
             <div class="col-md-4">
              <div class="mb-3">
                <label for="applying-role" class="form-label">Position Applied:</label>
                <select id="applying-role" class="form-select">
                  <option value="">--Select Position--</option>
                  <option value="research-analyst">Research Analyst</option>
                  <option value="operations-analyst">Operations Analyst</option>
                  <option value="financial-analyst">Financial Analyst</option>
                </select>
              </div>
            </div>
          </div>
        </div>

        <div class="d-flex justify-content-between mt-4">
          <a href="/" class="btn btn-outline-secondary">
            <i class="bi bi-arrow-left"></i> Back
          </a>
          <button class="btn btn-primary" onclick="nextStep(2)">
            Next <i class="bi bi-arrow-right"></i>
          </button>
        </div>
      </div>

      <!-- Step 2: Resume Evaluation -->
      <div class="tab-pane fade" id="step2" role="tabpanel">
        <div class="form-section">
          <h4><i class="bi bi-file-text"></i> Resume Evaluation</h4>
          <p class="text-muted mb-3">
            Please rate the applicant's resume based on relevant experience, education, and skills on a scale of 0-5.
          </p>
          <div id="resume-criteria-container">
            <!-- JavaScript will populate this based on selected position -->
          </div>
        </div>

          <div class="row">
            <div class="col-md-6 mx-auto">
              <label for="resume-score" class="form-label">Resume Score (0-5):</label>
              <input type="number" class="form-control form-control-lg text-center"
                     id="resume-score" min="0" max="5" step="0.1" placeholder="0.0 - 5.0">
              <div class="form-text text-center">
                0 = Poor, 5 = Excellent
              </div>
            </div>
          </div>
        </div>

        <div class="d-flex justify-content-between mt-4">
          <button class="btn btn-outline-secondary" onclick="prevStep(1)">
            <i class="bi bi-arrow-left"></i> Previous
          </button>
          <button class="btn btn-primary" onclick="nextStep(3)">
            Next <i class="bi bi-arrow-right"></i>
          </button>
        </div>
      </div>

      <!-- Step 3: Video Evaluation -->
      <div class="tab-pane fade" id="step3" role="tabpanel">
        <div class="form-section">
          <h4><i class="bi bi-camera-video"></i> Video Evaluation</h4>
          <p class="text-muted mb-3">
            Rate the applicant's video presentation (1-5 stars) based on the following criteria.
          </p>
"""

    # Manually build video evaluation section
    video_html = ""
    for group in video_criteria_list:
        video_html += f'<div class="criteria-section"><div class="criteria-title">{group["title"]}</div>'
        for item in group['items']:
            video_html += f'''
            <div class="sub-criteria">
              <div>
                <label>{item['label']} <span class="weight">{item['weight']}%</span></label>
              </div>
              <div class="star-rating" data-target="{item['id']}">
                <span data-value="1">&#9733;</span>
                <span data-value="2">&#9733;</span>
                <span data-value="3">&#9733;</span>
                <span data-value="4">&#9733;</span>
                <span data-value="5">&#9733;</span>
              </div>
              <input type="hidden" class="video-score" data-weight="{item['weight']}" id="{item['id']}" value="0">
            </div>
            '''
        video_html += '</div>'

    # Remaining HTML part
    tail_html = """
        </div>

        <div class="row mb-4">
          <div class="col-md-6">
            <div class="score-display">
              <div class="fw-bold">Content Quality</div>
              <div id="content-score-display" class="fs-4">0.0</div>
            </div>
          </div>
          <div class="col-md-6">
            <div class="score-display">
              <div class="fw-bold">Presentation Skills</div>
              <div id="presentation-score-display" class="fs-4">0.0</div>
            </div>
          </div>
        </div>

        

        <div class="d-flex justify-content-between mt-4">
          <button class="btn btn-outline-secondary" onclick="prevStep(2)">
            <i class="bi bi-arrow-left"></i> Previous
          </button>
          <button class="btn btn-primary" onclick="nextStep(4)">
            Next <i class="bi bi-arrow-right"></i>
          </button>
        </div>
      </div>

      <!-- Step 4: Final Decision -->
    <!-- Step 4: Final Decision -->
    <div class="tab-pane fade" id="step4" role="tabpanel">
      <!-- Result Card -->
      <div class="alert alert-info mb-4">
        <h5 class="mb-0">Based on your evaluations, the system has automatically recommended a decision</h5>
      </div>
      
      <!-- Evaluation Results -->
      <div class="result-section">
        <h4 class="text-center mb-3"><i class="bi bi-calculator"></i> Evaluation Results</h4>
        <div class="final-score mb-4">
          <i class="bi bi-award"></i> Final Score:
          <span id="final-score">0.0</span> / 5.0
        </div>
        <div class="row mb-4">
          <div class="col-md-4">
            <div class="score-display">
              <div class="fw-bold">Resume (40%)</div>
              <div id="resume-display" class="fs-4">0.0</div>
            </div>
          </div>
          <div class="col-md-4">
            <div class="score-display">
              <div class="fw-bold">Video (50%)</div>
              <div id="video-display" class="fs-4">0.0</div>
            </div>
          </div>
          <div class="col-md-4">
            <div class="score-display">
              <div class="fw-bold">Motivation (10%)</div>
              <div id="motivation-display" class="fs-4">0.0</div>
            </div>
          </div>
        </div>
      </div>
      
      <!-- Decision & Notes -->
      <div class="row mt-4">
        <div class="col-md-6 mx-auto">
          <div class="mb-3">
            <label for="decision" class="form-label fw-bold">Decision:</label>
            <select id="decision" class="form-select form-select-lg">
              <option value="">--Please Select--</option>
              <option value="advance">Advance to Next Round</option>
              <option value="waitlist">Add to Waitlist</option>
              <option value="reject">Reject</option>
            </select>
          </div>
    
          <div class="mb-3">
            <label for="notes" class="form-label fw-bold">Notes & Feedback:</label>
            <textarea id="notes" class="form-control" rows="4"
                      placeholder="Enter any additional notes or feedback for this applicant..."></textarea>
          </div>
        </div>
      </div>
    
      <!-- Button Area -->
      <div class="d-flex justify-content-between mt-4">
        <button class="btn btn-outline-secondary" onclick="prevStep(3)">
          <i class="bi bi-arrow-left"></i> Previous
        </button>
        <div>
          <button class="btn btn-danger me-2" id="resetBtn">
            <i class="bi bi-trash"></i> Reset
          </button>
          <button class="btn btn-success" id="saveBtn">
            <i class="bi bi-save"></i> Save Evaluation
          </button>
        </div>
      </div>
    </div>      
      
     
     
      
    
          <div class="row">
            <div class="col-md-6 mx-auto">
              <div class="mb-3">
                <label for="decision" class="form-label fw-bold">Decision:</label>
                <select id="decision" class="form-select form-select-lg">
                  <option value="">--Please Select--</option>
                  <option value="advance">Advance to Next Round</option>
                  <option value="waitlist">Add to Waitlist</option>
                  <option value="reject">Reject</option>
                </select>
              </div>

              <div class="mb-3">
                <label for="notes" class="form-label fw-bold">Notes & Feedback:</label>
                <textarea id="notes" class="form-control" rows="4"
                          placeholder="Enter any additional notes or feedback for this applicant..."></textarea>
              </div>
            </div>
          </div>
        </div>

        <div class="d-flex justify-content-between mt-4">
          <button class="btn btn-outline-secondary" onclick="prevStep(3)">
            <i class="bi bi-arrow-left"></i> Previous
          </button>
          <div>
            <button class="btn btn-danger me-2" id="resetBtn">
              <i class="bi bi-trash"></i> Reset
            </button>
            <button class="btn btn-success" id="saveBtn">
              <i class="bi bi-save"></i> Save Evaluation
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
  <script>
    document.addEventListener('DOMContentLoaded', () => {
      // Set default date
      document.getElementById('evaluation-date').valueAsDate = new Date();
      
      // Check if a position is already selected, apply scoring framework immediately if so
      setTimeout(() => {
        const position = document.getElementById('applying-role').value;
        if (position) {
          buildResumeCriteria();
          buildVideoCriteria();
          applyRoleWeights();
          updateScores();
        }
      }, 300);      
      
      // Update assessment criteria when position changes
      document.getElementById('applying-role').addEventListener('change', function() {
        updateResumeCriteria();      // Update resume criteria
        rebuildVideoCriteria();      // Rebuild video criteria
        applyRoleWeights();          // Apply position-specific weights
        updateScores();              // Update scores
      });
    
      // Initialize star ratings
      initializeStarRatings();
    
      // Initialize progress saving
      initProgressSaving();
    
      // Reset button
      document.getElementById('resetBtn').addEventListener('click', () => {
        if(!confirm('Are you sure you want to reset all evaluation data?')) return;
    
        document.getElementById('applicant-name').value = '';
        document.getElementById('applicant-id').value = '';
        document.getElementById('applying-role').selectedIndex = 0;
        document.getElementById('resume-score').value = '';
        document.getElementById('applicant-university').value = '';
        document.getElementById('applicant-email').value = '';
    
        document.querySelectorAll('.video-score, .resume-score, .motivation-score').forEach(inp => {
          inp.value = '0';
        });
    
        document.querySelectorAll('.star-rating span').forEach(star => {
          star.classList.remove('selected');
          star.style.color = '#ccc';
        });
    
        document.getElementById('decision').selectedIndex = 0;
        document.getElementById('notes').value = '';
    
        updateScores();
      });
    
      // Save evaluation
      document.getElementById('saveBtn').addEventListener('click', () => {
        // Input validation
        const requiredFields = [
          { id: 'applicant-name', name: 'Applicant Name' },
          { id: 'applicant-id', name: 'Applicant ID' },
          { id: 'applying-role', name: 'Position Applied' },
          { id: 'resume-score', name: 'Resume Score' },
          { id: 'decision', name: 'Decision' }
        ];
    
        let missingFields = [];
        requiredFields.forEach(field => {
          const value = document.getElementById(field.id).value;
          if (!value) missingFields.push(field.name);
        });
    
        if (missingFields.length > 0) {
          alert('Please complete the following required fields: ' + missingFields.join(', '));
          return;
        }
    
        // Collect data
        const judgeName = document.getElementById('judge-name').value || '';
        const judgeRole = document.getElementById('judge-role').value || '';
        const dateVal = document.getElementById('evaluation-date').value;
        const applicantName = document.getElementById('applicant-name').value || '';
        const applicantId = document.getElementById('applicant-id').value || '';
        const applicantRole = document.getElementById('applying-role').value || '';
        const applicantUniversity = document.getElementById('applicant-university').value || '';
        const applicantEmail = document.getElementById('applicant-email').value || '';
        const resumeScore = parseFloat(document.getElementById('resume-score').value) || 0;
        const videoScore = parseFloat(document.getElementById('video-display').textContent) || 0;
        const motivationScore = parseFloat(document.getElementById('motivation-display').textContent) || 0;
        const finalScore = parseFloat(document.getElementById('final-score').textContent) || 0;
        const decision = document.getElementById('decision').value || '';
        const notes = document.getElementById('notes').value || '';
    
        if (applicantEmail && !applicantEmail.includes('@')) {
        　alert('Please enter a valid email address');
        　return;
        }
    
        // Collect video ratings
        const videoRatings = {};
        document.querySelectorAll('.video-score').forEach(inp => {
          if(inp.id){
            videoRatings[inp.id] = {
              score: parseFloat(inp.value) || 0,
              weight: parseFloat(inp.dataset.weight) || 0
            };
          }
        });
    
        // Collect resume ratings
        const resumeRatings = {};
        document.querySelectorAll('.resume-score').forEach(inp => {
          if(inp.id){
            resumeRatings[inp.id] = {
              score: parseFloat(inp.value) || 0,
              weight: parseFloat(inp.dataset.weight) || 0
            };
          }
        });
    
        // Collect motivation rating (ensure it's only collected once)
        const motivationInput = document.getElementById('motivation_enthusiasm');
        if (motivationInput) {
          videoRatings['motivation_enthusiasm'] = {
            score: parseFloat(motivationInput.value) || 0,
            weight: 10
          };
        }
    
        const payload = {
          judge_name: judgeName,
          judge_role: judgeRole,
          evaluation_date: dateVal,
          applicant_name: applicantName,
          applicant_id: applicantId,
          applicant_role: applicantRole,
          applicant_university: applicantUniversity,
          applicant_email: applicantEmail,
          resume_score: resumeScore.toFixed(1),
          resume_ratings: resumeRatings,
          video_score: videoScore.toFixed(1),
          video_ratings: videoRatings,
          motivation_score: motivationScore.toFixed(1),
          final_score: finalScore.toFixed(1),
          decision: decision,
          notes: notes
        };
    
        // Submit data
        fetch('/api/save-rating', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify(payload)
        })
        .then(res => res.json())
        .then(data => {
          if(data.error){
            alert('Save failed: ' + data.error);
          } else {
            alert('Evaluation saved successfully! Record ID: ' + data.evaluation_id);
    
            // Redirect or clear form
            if (confirm('Would you like to evaluate another applicant?')) {
              // Reset form data directly without additional confirmation
              document.getElementById('applicant-name').value = '';
              document.getElementById('applicant-id').value = '';
              document.getElementById('applicant-university').value = '';
              document.getElementById('applicant-email').value = '';
              document.getElementById('applying-role').selectedIndex = 0;
              document.getElementById('resume-score').value = '';
    
              document.querySelectorAll('.video-score, .resume-score, .motivation-score').forEach(inp => {
                inp.value = '0';
              });
    
              document.querySelectorAll('.star-rating span').forEach(star => {
                star.classList.remove('selected');
                star.style.color = '#ccc';
              });
    
              document.getElementById('decision').selectedIndex = 0;
              document.getElementById('notes').value = '';
    
              // Clear saved progress
              sessionStorage.removeItem('evaluation-progress');
    
              // Redirect to home page
              window.location.href = '/';
            } else {
              window.location.href = '/evaluations';
            }
          }
        })
        .catch(error => {
          alert('An error occurred during save: ' + error);
        });
      });
    
      // Set default weights
      setTimeout(() => {
        document.querySelectorAll('.video-score').forEach(input => {
          if (!input.hasAttribute('data-base-weight')) {
            input.setAttribute('data-base-weight', input.dataset.weight);
          }
        });
    
        // If position is selected, create video evaluation section
        const position = document.getElementById('applying-role').value;
        if (position) {
          buildResumeCriteria();
          buildVideoCriteria();
          applyRoleWeights();
        }
      }, 500);
    
      // Add skill type explanations
      setTimeout(addSkillTypeHelp, 1000);
    });    
    
    
    
    
    // --- Helper Functions ---
  // If more complex logic is needed later, expand these functions
  function updateResumeCriteria() {
    buildResumeCriteria();
  }
  function buildResumeCriteria() {
    applyRoleWeights();
  }
  
  
  
  

    // Star rating functionality
    function initializeStarRatings() {
      const starGroups = document.querySelectorAll('.star-rating');
      starGroups.forEach(group => {
        let currentScore = 0;
        const stars = group.querySelectorAll('span');
        const targetId = group.dataset.target;
        const hiddenInput = document.getElementById(targetId);

        group.addEventListener('mouseover', e => {
          if(e.target.dataset.value){
            highlightStars(stars, e.target.dataset.value);
          }
        });

        group.addEventListener('mouseout', () => {
          highlightStars(stars, currentScore);
        });

        group.addEventListener('click', e => {
          if(e.target.dataset.value){
            currentScore = parseInt(e.target.dataset.value);
            hiddenInput.value = currentScore;
            highlightStars(stars, currentScore);
            updateScores();
          }
        });
      });
    }

    function highlightStars(stars, score){
      stars.forEach(star => {
        const val = parseInt(star.dataset.value);
        star.style.color = (val <= score) ? '#FFC107' : '#ccc';
        if(val <= score){
          star.classList.add('selected');
        } else {
          star.classList.remove('selected');
        }
      });
    }

    // Get resume evaluation criteria
    function getResumeVCCriteria(position) {
      const criteria = [
        {
          title: "Hard Skills Assessment",
          items: [
            {id: "resume_technical", weight: 15, label: "Technical Proficiency", type: "hard",
             description: "Relevant courses, technical training, and professional knowledge"},
            {id: "resume_experience", weight: 10, label: "Relevant Experience", type: "hard",
             description: "Relevant internships and project experience"}
          ]
        },
        {
          title: "Soft Skills Assessment",
          items: [
            {id: "resume_leadership", weight: 10, label: "Extracurricular & Leadership", type: "soft",
             description: "Team collaboration, activity participation, and leadership experience"},
            {id: "resume_presentation", weight: 5, label: "Resume Presentation", type: "soft",
             description: "Resume format, organization, and professional presentation"}
          ]
        }
      ];

      
    // Adjust labels based on position
      if (position === "financial-analyst") {
        criteria[0].items[0].label = "Financial Modeling & Valuation";
        criteria[0].items[0].description = "Financial modeling, valuation analysis, and investment return calculation";
        criteria[0].items[1].label = "Financial Analysis & Investment Experience";
        criteria[0].items[1].description = "Financial analysis, due diligence, and investment justification";
        criteria[1].items[0].label = "Networking & Relationship Building";
        criteria[1].items[0].description = "Industry network building and investor relations management";
      }
      else if (position === "research-analyst") {
        criteria[0].items[0].label = "Market & Industry Trend Analysis";
        criteria[0].items[0].description = "Market intelligence gathering and industry trend analysis";
        criteria[0].items[1].label = "Data Analysis & Research Methods";
        criteria[0].items[1].description = "Data analysis tools and research methodology application";
        criteria[1].items[0].label = "Learning Agility for Emerging Trends";
        criteria[1].items[0].description = "Adaptability and acuity in identifying emerging trends";
      }
      else if (position === "operations-analyst") {
        criteria[0].items[0].label = "Business Process Optimization";
        criteria[0].items[0].description = "Business process analysis and optimization design";
        criteria[0].items[1].label = "Project Management & Operations";
        criteria[0].items[1].description = "Project management and business operations support";
        criteria[1].items[0].label = "Adaptability & Problem Solving";
        criteria[1].items[0].description = "Adaptability to challenges and innovative solution development";
      }
      return criteria;
    }

    // Get video evaluation criteria
    function getVideoVCCriteria(position) {
      const criteria = [
        {
          title: "Content Quality Assessment (25%)",
          items: [
            {id: "content_understanding", weight: 12.5, label: "Product & Market Understanding", type: "hard",
             description: "Analysis of Sertie's value proposition and market opportunities"},
            {id: "content_marketing", weight: 12.5, label: "Marketing Strategy Analysis", type: "hard",
             description: "Evaluation of current marketing and Premium Service promotion plan"}
          ]
        },
        {
          title: "Presentation Skills Assessment (25%)",
          items: [
            {id: "presentation_creativity", weight: 8.33, label: "Creative Expression", type: "soft",
             description: "Uniqueness of video format and personal style presentation"},
            {id: "presentation_clarity", weight: 8.33, label: "Communication Clarity", type: "soft",
             description: "Accuracy and fluency of information delivery"},
            {id: "presentation_structure", weight: 8.33, label: "Structure & Time Management", type: "soft",
             description: "Completeness of content organization and reasonable time allocation within 3 minutes"}
          ]
        }
      ];

      
// Adjust assessment focus based on position
      if (position === "financial-analyst") {
        criteria[0].items[0].description += ", with focus on business model and profitability analysis";
        criteria[0].items[1].description += ", with focus on ROI and budget allocation analysis";
        criteria[1].items[1].label = "Investment Proposal Presentation";
        criteria[1].items[1].description = "Clarity and persuasiveness of investment logic presentation";
      }
      else if (position === "research-analyst") {
        criteria[0].items[0].description += ", with focus on market opportunity assessment and data support";
        criteria[0].items[1].description += ", with focus on target user insights and effect prediction";
        criteria[1].items[1].label = "Research Findings Presentation";
        criteria[1].items[1].description = "Clarity of research conclusions and insights presentation";
      }
      else if (position === "operations-analyst") {
        criteria[0].items[0].description += ", with focus on service improvement and user experience optimization";
        criteria[0].items[1].description += ", with focus on execution planning and operability";
        criteria[1].items[1].label = "Stakeholder Management";
        criteria[1].items[1].description = "Clarity and effectiveness of communication with various parties";
      }
    
      return criteria;
    }


    // Get weight factors for each position
    function getRoleWeights(position) {
      if (position === "financial-analyst") {
        return { hard: 0.7, soft: 0.3 };
      }
      else if (position === "research-analyst") {
        return { hard: 0.4, soft: 0.6 };
      }
      else if (position === "operations-analyst") {
        return { hard: 0.2, soft: 0.8 };
      }

      // Default to balanced weights
      return { hard: 0.5, soft: 0.5 };
    }

    // Build resume evaluation section
    function buildResumeCriteria() {
      const position = document.getElementById('applying-role').value;
      const container = document.getElementById('resume-criteria-container');

      if (!position) {
        container.innerHTML = '<p class="text-muted">Please select a position first to display relevant criteria</p>';
        return;
      }

      // Get position weights
      const weights = getRoleWeights(position);
      const hardWeight = weights.hard * 100;
      const softWeight = weights.soft * 100;

      // Get evaluation criteria
      const criteria = getResumeVCCriteria(position);

      // Build HTML
      let html = `
        <div class="alert alert-info">
          <i class="bi bi-info-circle"></i> <strong>${getPositionName(position)}</strong>
          Weight Distribution: Hard Skills ${hardWeight}% / Soft Skills ${softWeight}%
        </div>
      `;

      // Scoring reference
      html += `
        <div class="mb-3 small text-muted">
          <strong>Scoring Reference:</strong>
          <span class="badge bg-danger">1★</span> Does not meet requirements
          <span class="badge bg-warning text-dark">2★</span> Meets basic requirements
          <span class="badge bg-primary">3★</span> Meets expectations
          <span class="badge bg-info">4★</span> Exceeds expectations
          <span class="badge bg-success">5★</span> Outstanding performance
        </div>
      `;

      // Build each evaluation item
      criteria.forEach(group => {
        html += `<div class="criteria-section"><div class="criteria-title">${group.title}</div>`;

        group.items.forEach(item => {
          const itemType = item.type === "hard" ? "Hard Skill" : "Soft Skill";
          const typeClass = item.type === "hard" ? "badge bg-danger" : "badge bg-success";

          html += `
            <div class="sub-criteria">
              <div>
                <label>${item.label} <span class="weight">${item.weight}%</span></label>
                <span class="${typeClass} ms-2">${itemType}</span>
                <div class="small text-muted">${item.description}</div>
              </div>
              <div class="star-rating" data-target="${item.id}">
                <span data-value="1" title="Does not meet requirements">&#9733;</span>
                <span data-value="2" title="Meets basic requirements">&#9733;</span>
                <span data-value="3" title="Meets expectations">&#9733;</span>
                <span data-value="4" title="Exceeds expectations">&#9733;</span>
                <span data-value="5" title="Outstanding performance">&#9733;</span>
              </div>
              <input type="hidden" class="resume-score"
                     data-weight="${item.weight}"
                     data-type="${item.type}"
                     id="${item.id}" value="0">
            </div>
          `;
        });

        html += '</div>';
      });

      container.innerHTML = html;
      initializeStarRatings();
    }

    // Build video evaluation section
    function buildVideoCriteria() {
      const position = document.getElementById('applying-role').value;
      if (!position) return;
    
      // Get video evaluation section container
      const videoSection = document.querySelector('#step3 .form-section');
      if (!videoSection) return;
    
      // Get position weights
      const weights = getRoleWeights(position);
      const hardWeight = weights.hard * 100;
      const softWeight = weights.soft * 100;
    
      // Video evaluation criteria
      const criteria = getVideoVCCriteria(position);
    
      // Build HTML
      let html = `
        <h4><i class="bi bi-camera-video"></i> Video Evaluation</h4>
        <p class="text-muted mb-3">Rate the applicant's video performance on the following criteria (1-5 stars).</p>
    
        <div class="alert alert-info">
          <i class="bi bi-info-circle"></i> <strong>${getPositionName(position)}</strong>
          Weight Distribution: Hard Skills ${hardWeight}% / Soft Skills ${softWeight}%
        </div>
    
        <div class="mb-3 small text-muted">
          <strong>Scoring Reference:</strong>
          <span class="badge bg-danger">1★</span> Does not meet requirements
          <span class="badge bg-warning text-dark">2★</span> Meets basic requirements
          <span class="badge bg-primary">3★</span> Meets expectations
          <span class="badge bg-info">4★</span> Exceeds expectations
          <span class="badge bg-success">5★</span> Outstanding performance
        </div>
      `;
    
      // Build evaluation items
      criteria.forEach(group => {
        html += `<div class="criteria-section"><div class="criteria-title">${group.title}</div>`;
    
        group.items.forEach(item => {
          const itemType = item.type === "hard" ? "Hard Skill" : "Soft Skill";
          const typeClass = item.type === "hard" ? "badge bg-danger" : "badge bg-success";
    
          html += `
            <div class="sub-criteria">
              <div>
                <label>${item.label} <span class="weight">${item.weight}%</span></label>
                <span class="${typeClass} ms-2">${itemType}</span>
                <div class="small text-muted">${item.description}</div>
              </div>
              <div class="star-rating" data-target="${item.id}">
                <span data-value="1" title="Does not meet requirements">&#9733;</span>
                <span data-value="2" title="Meets basic requirements">&#9733;</span>
                <span data-value="3" title="Meets expectations">&#9733;</span>
                <span data-value="4" title="Exceeds expectations">&#9733;</span>
                <span data-value="5" title="Outstanding performance">&#9733;</span>
              </div>
              <input type="hidden" class="video-score"
                     data-weight="${item.weight}"
                     data-type="${item.type}"
                     id="${item.id}" value="0">
            </div>
          `;
        });
    
        html += '</div>';
      });
    
      // Add detailed score display section
      html += `
        <div class="row mb-4">
          <div class="col-md-4">
            <div class="score-display">
              <div class="fw-bold">Hard Skills Score</div>
              <div id="hard-skills-display" class="fs-4">0.0</div>
            </div>
          </div>
          <div class="col-md-4">
            <div class="score-display">
              <div class="fw-bold">Soft Skills Score</div>
              <div id="soft-skills-display" class="fs-4">0.0</div>
            </div>
          </div>
          <div class="col-md-4">
            <div class="score-display">
              <div class="fw-bold">Video Total</div>
              <div id="video-total-display" class="fs-4">0.0</div>
            </div>
          </div>
        </div>
      `;
    
      // Set container content
      videoSection.innerHTML = html;
    
      // Remove existing motivation section (if any)
      const existingMotivationSection = document.getElementById('motivation-section');
      if (existingMotivationSection) {
        existingMotivationSection.remove();
      }
    
      // Add motivation assessment section
      const motivationHtml = `
        <div class="form-section" id="motivation-section">
          <h4><i class="bi bi-heart"></i> Motivation Assessment (10%)</h4>
          <p class="text-muted mb-3">
            Please assess the applicant's enthusiasm and fit for the position (1-5 stars).
          </p>
    
          <div class="sub-criteria">
            <div>
              <label>Career Plan Alignment <span class="weight">10%</span></label>
              <div class="small text-muted">Position understanding, career development plan alignment, and learning motivation</div>
            </div>
            <div class="star-rating" data-target="motivation_enthusiasm">
              <span data-value="1" title="Does not meet requirements">&#9733;</span>
              <span data-value="2" title="Meets basic requirements">&#9733;</span>
              <span data-value="3" title="Meets expectations">&#9733;</span>
              <span data-value="4" title="Exceeds expectations">&#9733;</span>
              <span data-value="5" title="Outstanding performance">&#9733;</span>
            </div>
            <input type="hidden" id="motivation_enthusiasm" class="motivation-score" data-weight="10" value="0">
          </div>
          
          <!-- Add motivation score display -->
          <div class="row mt-4">
            <div class="col-md-6 mx-auto">
              <div class="score-display text-center">
                <div class="fw-bold">Motivation Score</div>
                <div id="motivation-total-display" class="fs-4">0.0</div>
              </div>
            </div>
          </div>
        </div>
      `;
    
      // Add motivation assessment section
      videoSection.insertAdjacentHTML('afterend', motivationHtml);
    
      // Initialize star ratings
      initializeStarRatings();
    }


    
    // New function: Rebuild video evaluation section when position changes
    function rebuildVideoCriteria() {
      // Clear current video evaluation section
      const videoSection = document.querySelector('#step3 .form-section');
      if (videoSection) {
        videoSection.innerHTML = '';
      }
      
      // Remove current motivation assessment section (if exists)
      const motivationSection = document.getElementById('motivation-section');
      if (motivationSection) {
        motivationSection.remove();
      }
      
      // Rebuild video evaluation section
      buildVideoCriteria();
      
      // Reinitialize star ratings
      initializeStarRatings();
    }

    // Apply position-specific weights
    function applyRoleWeights() {
      const position = document.getElementById('applying-role').value;
      if (!position) return;

      // Get position-specific weights
      const weights = getRoleWeights(position);

      // Apply to resume evaluation
      applyWeightsToType('.resume-score', weights);

      // Apply to video evaluation
      applyWeightsToType('.video-score', weights);
    }

    // Apply weights by type
    function applyWeightsToType(selector, weights) {
      // Store original weights (if not already stored)
      document.querySelectorAll(selector).forEach(input => {
        if (!input.hasAttribute('data-base-weight')) {
          input.setAttribute('data-base-weight', input.dataset.weight);
        }
      });

      // Calculate hard skills original total weight
      let hardTotalBaseWeight = 0;
      document.querySelectorAll(`${selector}[data-type="hard"]`).forEach(input => {
        hardTotalBaseWeight += parseFloat(input.getAttribute('data-base-weight') || 0);
      });

      // Calculate soft skills original total weight
      let softTotalBaseWeight = 0;
      document.querySelectorAll(`${selector}[data-type="soft"]`).forEach(input => {
        softTotalBaseWeight += parseFloat(input.getAttribute('data-base-weight') || 0);
      });

      // Apply hard skills weight
      if (hardTotalBaseWeight > 0) {
        const hardMultiplier = (selector.includes('resume') ? 0.4 : 0.5) * weights.hard / hardTotalBaseWeight;
        document.querySelectorAll(`${selector}[data-type="hard"]`).forEach(input => {
          const baseWeight = parseFloat(input.getAttribute('data-base-weight') || 0);
          const adjustedWeight = baseWeight * hardMultiplier;
          input.dataset.weight = adjustedWeight.toFixed(2);

          // Update UI display
          const weightSpan = input.closest('.sub-criteria')?.querySelector('.weight');
          if (weightSpan) {
            weightSpan.textContent = `${adjustedWeight.toFixed(2)}%`;
          }
        });
      }

      // Apply soft skills weight
      if (softTotalBaseWeight > 0) {
        const softMultiplier = (selector.includes('resume') ? 0.4 : 0.5) * weights.soft / softTotalBaseWeight;
        document.querySelectorAll(`${selector}[data-type="soft"]`).forEach(input => {
          const baseWeight = parseFloat(input.getAttribute('data-base-weight') || 0);
          const adjustedWeight = baseWeight * softMultiplier;
          input.dataset.weight = adjustedWeight.toFixed(2);

          // Update UI display
          const weightSpan = input.closest('.sub-criteria')?.querySelector('.weight');
          if (weightSpan) {
            weightSpan.textContent = `${adjustedWeight.toFixed(2)}%`;
          }
        });
      }
    }

    // Calculate scores
    function updateScores() {
      // Calculate resume hard skills score
      let resumeHardWeightedSum = 0;
      let resumeHardTotalWeight = 0;
      document.querySelectorAll('.resume-score[data-type="hard"]').forEach(input => {
        const score = parseFloat(input.value) || 0;
        const weight = parseFloat(input.dataset.weight) || 0;
        resumeHardWeightedSum += score * weight;
        resumeHardTotalWeight += weight;
      });
    
      // Calculate resume soft skills score
      let resumeSoftWeightedSum = 0;
      let resumeSoftTotalWeight = 0;
      document.querySelectorAll('.resume-score[data-type="soft"]').forEach(input => {
        const score = parseFloat(input.value) || 0;
        const weight = parseFloat(input.dataset.weight) || 0;
        resumeSoftWeightedSum += score * weight;
        resumeSoftTotalWeight += weight;
      });
    
      // Calculate video hard skills score
      let videoHardWeightedSum = 0;
      let videoHardTotalWeight = 0;
      document.querySelectorAll('.video-score[data-type="hard"]').forEach(input => {
        const score = parseFloat(input.value) || 0;
        const weight = parseFloat(input.dataset.weight) || 0;
        videoHardWeightedSum += score * weight;
        videoHardTotalWeight += weight;
      });
    
      // Calculate video soft skills score
      let videoSoftWeightedSum = 0;
      let videoSoftTotalWeight = 0;
      document.querySelectorAll('.video-score[data-type="soft"]').forEach(input => {
        const score = parseFloat(input.value) || 0;
        const weight = parseFloat(input.dataset.weight) || 0;
        videoSoftWeightedSum += score * weight;
        videoSoftTotalWeight += weight;
      });
    
      // Calculate totals
      const resumeTotalWeight = resumeHardTotalWeight + resumeSoftTotalWeight;
      const resumeAvg = resumeTotalWeight > 0 ?
        (resumeHardWeightedSum + resumeSoftWeightedSum) / resumeTotalWeight * 10 : 0;
    
      const videoTotalWeight = videoHardTotalWeight + videoSoftTotalWeight;
      const videoAvg = videoTotalWeight > 0 ?
        (videoHardWeightedSum + videoSoftWeightedSum) / videoTotalWeight * 10 : 0;
    
      // Calculate hard and soft skills averages
      const hardSkillsAvg = (videoHardTotalWeight > 0) ?
        (videoHardWeightedSum / videoHardTotalWeight * 5) : 0; // 0-5 scale
      const softSkillsAvg = (videoSoftTotalWeight > 0) ?
        (videoSoftWeightedSum / videoSoftTotalWeight * 5) : 0; // 0-5 scale
    
      // Calculate content quality and presentation skills
      // Find all content quality related ratings
      let contentQualitySum = 0;
      let contentQualityCount = 0;
      document.querySelectorAll('.video-score[id^="content_"]').forEach(input => {
        const score = parseFloat(input.value) || 0;
        if (score > 0) {
          contentQualitySum += score;
          contentQualityCount++;
        }
      });
      
      // Find all presentation skills related ratings
      let presentationSkillsSum = 0;
      let presentationSkillsCount = 0;
      document.querySelectorAll('.video-score[id^="presentation_"]').forEach(input => {
        const score = parseFloat(input.value) || 0;
        if (score > 0) {
          presentationSkillsSum += score;
          presentationSkillsCount++;
        }
      });
      
      // Calculate averages
      const contentQualityAvg = contentQualityCount > 0 ? contentQualitySum / contentQualityCount : 0;
      const presentationSkillsAvg = presentationSkillsCount > 0 ? presentationSkillsSum / presentationSkillsCount : 0;
    
      // Update resume score display
      document.getElementById('resume-display').textContent = (resumeAvg / 10).toFixed(1);
      document.getElementById('resume-score').value = (resumeAvg / 10).toFixed(1);
      
      // Update hard/soft skills score display
      const hardSkillsDisplay = document.getElementById('hard-skills-display');
      const softSkillsDisplay = document.getElementById('soft-skills-display');
      const videoTotalDisplay = document.getElementById('video-total-display');
      
      if (hardSkillsDisplay) {
        hardSkillsDisplay.textContent = hardSkillsAvg.toFixed(1);
      }
      
      if (softSkillsDisplay) {
        softSkillsDisplay.textContent = softSkillsAvg.toFixed(1);
      }
      
      if (videoTotalDisplay) {
        videoTotalDisplay.textContent = (videoAvg / 10).toFixed(1);
      }
      
      // Update content quality and presentation skills display
      const contentScoreDisplay = document.getElementById('content-score-display');
      const presentationScoreDisplay = document.getElementById('presentation-score-display');
      
      if (contentScoreDisplay) {
        contentScoreDisplay.textContent = contentQualityAvg.toFixed(1);
      }
      
      if (presentationScoreDisplay) {
        presentationScoreDisplay.textContent = presentationSkillsAvg.toFixed(1);
      }
      
      // Update video score in final page display
      document.getElementById('video-display').textContent = (videoAvg / 10).toFixed(1);
    
      // Calculate motivation score - ensure it's only collected once
      const motivationInput = document.getElementById('motivation_enthusiasm');
      const motivationScore = motivationInput ? (parseFloat(motivationInput.value) || 0) : 0;
      
      // Update motivation score display
      document.getElementById('motivation-display').textContent = motivationScore.toFixed(1);
      
      // Update motivation total display (if exists)
      const motivationTotalDisplay = document.getElementById('motivation-total-display');
      if (motivationTotalDisplay) {
        motivationTotalDisplay.textContent = motivationScore.toFixed(1);
      }
    
      // Calculate final weighted score - maintain 4:5:1 ratio
      const finalScore = ((resumeAvg * 0.4) + (videoAvg * 0.5) + (motivationScore * 10 * 0.1)) / 10;
    
      // Update final score
      const fsElem = document.getElementById('final-score');
      fsElem.textContent = finalScore.toFixed(1);
      
      // Update weight description
      const position = document.getElementById('applying-role').value;
      if (position) {
        const weights = getRoleWeights(position);
        
        // Remove old weight info
        const oldWeightInfo = document.querySelector('.weight-info');
        if (oldWeightInfo) {
          oldWeightInfo.remove();
        }
        
        // Add new weight info
        const weightInfo = document.createElement('div');
        weightInfo.className = 'text-center text-muted mt-2 mb-3 weight-info';
        weightInfo.innerHTML = `Based on ${getPositionName(position)} role weights: Hard Skills ${weights.hard*100}% / Soft Skills ${weights.soft*100}%, with Resume(40%), Video(50%), Motivation(10%)`;
        
        if (fsElem.parentNode) {
          fsElem.parentNode.after(weightInfo);
        }
      } 
    
      // Set color based on score
      const fsVal = parseFloat(finalScore.toFixed(1));
      if (fsVal >= 4.5) fsElem.style.color = '#1E8449';
      else if (fsVal >= 4.0) fsElem.style.color = '#27AE60';
      else if (fsVal >= 3.5) fsElem.style.color = '#2E86C1';
      else if (fsVal >= 3.0) fsElem.style.color = '#F39C12';
      else fsElem.style.color = '#E74C3C';
    
      // Suggest decision based on score
      suggestDecision(fsVal);
    }

    
    // Add scoring guide
    function addScoringGuide() {
      const guideContent = `
        <div class="modal fade" id="scoringGuideModal" tabindex="-1">
          <div class="modal-dialog modal-lg">
            <div class="modal-content">
              <div class="modal-header bg-primary text-white">
                <h5 class="modal-title">Scoring Guide</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
              </div>
              <div class="modal-body">
                <h6>Scoring Criteria Explanation</h6>
                <div class="table-responsive">
                  <table class="table table-bordered">
                    <thead>
                      <tr>
                        <th>Score</th>
                        <th>Resume Evaluation</th>
                        <th>Video Evaluation</th>
                        <th>Motivation Evaluation</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td><span class="badge bg-danger">1★</span> Does not meet requirements</td>
                        <td>Almost no relevant skills or experience</td>
                        <td>Shallow product understanding, inadequate analysis</td>
                        <td>Unclear motivation, lacks position understanding</td>
                      </tr>
                      <tr>
                        <td><span class="badge bg-warning text-dark">2★</span> Meets basic requirements</td>
                        <td>Basic relevant experience, limited responsibilities</td>
                        <td>Basic product understanding, somewhat limited analysis</td>
                        <td>Basic interest, limited position understanding</td>
                      </tr>
                      <tr>
                        <td><span class="badge bg-primary">3★</span> Meets expectations</td>
                        <td>Relevant academic background, team role experience</td>
                        <td>Understands core value, offers effective suggestions</td>
                        <td>Shows clear interest, reasonable position understanding</td>
                      </tr>
                      <tr>
                        <td><span class="badge bg-info">4★</span> Exceeds expectations</td>
                        <td>Multiple high-quality relevant experiences, clear achievements</td>
                        <td>Deep product understanding, creative and viable proposals</td>
                        <td>High alignment, clearly articulates personal fit</td>
                      </tr>
                      <tr>
                        <td><span class="badge bg-success">5★</span> Outstanding performance</td>
                        <td>Exceptional technical skills, special achievements</td>
                        <td>Comprehensive analysis, innovative high-ROI solutions</td>
                        <td>Perfect fit, shows well-thought career planning</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <h6 class="mt-4">Position-Specific Assessment Focus</h6>
                <div class="accordion" id="positionAccordion">
                  <div class="accordion-item">
                    <h2 class="accordion-header">
                      <button class="accordion-button" type="button" data-bs-toggle="collapse" data-bs-target="#financeContent">
                        Financial Analyst (Hard Skills 70%, Soft Skills 30%)
                      </button>
                    </h2>
                    <div id="financeContent" class="accordion-collapse collapse show" data-bs-parent="#positionAccordion">
                      <div class="accordion-body">
                        <p><strong>Hard Skills Focus:</strong> Financial modeling and valuation skills, financial analysis, due diligence and risk assessment</p>
                        <p><strong>Soft Skills Focus:</strong> Communication with portfolio companies, investment proposal presentation, networking and relationship building</p>
                      </div>
                    </div>
                  </div>
                  <div class="accordion-item">
                    <h2 class="accordion-header">
                      <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#researchContent">
                        Research Analyst (Hard Skills 40%, Soft Skills 60%)
                      </button>
                    </h2>
                    <div id="researchContent" class="accordion-collapse collapse" data-bs-parent="#positionAccordion">
                      <div class="accordion-body">
                        <p><strong>Hard Skills Focus:</strong> Market and industry trend analysis, data analysis, technology assessment and competitive landscape analysis</p>
                        <p><strong>Soft Skills Focus:</strong> Critical thinking and insight, clear research findings presentation, learning agility for emerging trends</p>
                      </div>
                    </div>
                  </div>
                  <div class="accordion-item">
                    <h2 class="accordion-header">
                      <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#opsContent">
                        Operations Analyst (Hard Skills 20%, Soft Skills 80%)
                      </button>
                    </h2>
                    <div id="opsContent" class="accordion-collapse collapse" data-bs-parent="#positionAccordion">
                      <div class="accordion-body">
                        <p><strong>Hard Skills Focus:</strong> Business process analysis, KPI development and monitoring, project management and business operations</p>
                        <p><strong>Soft Skills Focus:</strong> Cross-functional collaboration, stakeholder management, adaptability and problem-solving</p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      `;

      // Add to page
      document.body.insertAdjacentHTML('beforeend', guideContent);

      // Add guide button
      const header = document.querySelector('.container h1');
      if (header) {
        const guideButton = document.createElement('button');
        guideButton.className = 'btn btn-sm btn-outline-info ms-3';
        guideButton.innerHTML = '<i class="bi bi-question-circle"></i> Scoring Guide';
        guideButton.addEventListener('click', () => {
          new bootstrap.Modal(document.getElementById('scoringGuideModal')).show();
        });
        header.insertAdjacentElement('afterend', guideButton);
      }
    }
    
    // Get position name
    function getPositionName(position) {
      switch(position) {
        case 'financial-analyst': return 'Financial Analyst';
        case 'research-analyst': return 'Research Analyst';
        case 'operations-analyst': return 'Operations Analyst';
        default: return 'Applicant';
      }
    }
    
    // Suggest decision based on score
    function suggestDecision(score) {
      const decisionSelect = document.getElementById('decision');
      if (score >= 4.0) {
        decisionSelect.value = 'advance';
      } else if (score >= 3.0) {
        decisionSelect.value = 'waitlist';
      } else {
        decisionSelect.value = 'reject';
      }
    }
    
    // Step navigation functions
    function nextStep(step) {
      // Form validation
      if (step === 2) {
        const applicantName = document.getElementById('applicant-name').value;
        const applicantId = document.getElementById('applicant-id').value;
        const applicantRole = document.getElementById('applying-role').value;
    
        if (!applicantName || !applicantId || !applicantRole) {
          alert('Please complete all required applicant information before continuing.');
          return;
        }
      }
    
      if (step === 3) {
        const resumeScore = document.getElementById('resume-score').value;
        if (!resumeScore) {
          alert('Please provide a resume score before continuing.');
          return;
        }
      }
    
      // Update progress bar
      const progressBar = document.getElementById('progressBar');
      progressBar.style.width = (step * 25) + '%';
    
      // Activate appropriate tab
      const tabToActivate = document.getElementById('step' + step + '-tab');
      bootstrap.Tab.getOrCreateInstance(tabToActivate).show();
    }
    
    function prevStep(step) {
      // Update progress bar
      const progressBar = document.getElementById('progressBar');
      progressBar.style.width = (step * 25) + '%';
    
      // Activate appropriate tab
      const tabToActivate = document.getElementById('step' + step + '-tab');
      bootstrap.Tab.getOrCreateInstance(tabToActivate).show();
    }
    
    // Progress saving functions
    function initProgressSaving() {
      // Load saved progress if exists
      loadSavedProgress();
    
      // Save progress every 30 seconds
      setInterval(saveProgress, 30000);
    
      // Save progress when switching tabs
      document.querySelectorAll('[data-bs-toggle="pill"]').forEach(tab => {
        tab.addEventListener('shown.bs.tab', saveProgress);
      });
    
      // Add save indicator
      const container = document.querySelector('.container');
      const saveIndicator = document.createElement('div');
      saveIndicator.id = 'save-indicator';
      saveIndicator.style = 'position: fixed; bottom: 20px; right: 20px; padding: 10px; background: #28a745; color: white; border-radius: 5px; opacity: 0; transition: opacity 0.3s;';
      saveIndicator.innerHTML = '<i class="bi bi-check-circle"></i> Progress saved';
      container.appendChild(saveIndicator);
    }
    
    function saveProgress() {
      const formData = {
        step: getActiveStepIndex(),
        applicantName: document.getElementById('applicant-name').value,
        applicantId: document.getElementById('applicant-id').value,
        applicantRole: document.getElementById('applying-role').value,
        applicantUniversity: document.getElementById('applicant-university').value,
        applicantEmail: document.getElementById('applicant-email').value,
        resumeScore: document.getElementById('resume-score').value,
        videoScores: collectScores('video-score'),
        resumeScores: collectScores('resume-score'),
        motivationScore: document.getElementById('motivation_enthusiasm')?.value,
        decision: document.getElementById('decision').value,
        notes: document.getElementById('notes').value
      };
    
      sessionStorage.setItem('evaluation-progress', JSON.stringify(formData));
      showSaveIndicator();
    }
    
    function loadSavedProgress() {
      const savedData = sessionStorage.getItem('evaluation-progress');
      if (!savedData) return;
    
      const formData = JSON.parse(savedData);
    
      // Restore form values
      setFieldValue('applicant-name', formData.applicantName);
      setFieldValue('applicant-id', formData.applicantId);
      setFieldValue('applying-role', formData.applicantRole);
      setFieldValue('applicant-university', formData.applicantUniversity);
      setFieldValue('applicant-email', formData.applicantEmail);
      setFieldValue('resume-score', formData.resumeScore);
      setFieldValue('decision', formData.decision);
      setFieldValue('notes', formData.notes);
    
      // Restore scores
      restoreScores(formData.videoScores, 'video-score');
      restoreScores(formData.resumeScores, 'resume-score');
      setFieldValue('motivation_enthusiasm', formData.motivationScore);
    
      // Add notification
      const notice = document.createElement('div');
      notice.className = 'alert alert-info alert-dismissible fade show';
      notice.innerHTML = '<i class="bi bi-info-circle"></i> Previous progress has been restored <button type="button" class="btn-close" data-bs-dismiss="alert"></button>';
      document.querySelector('.container').insertBefore(notice, document.querySelector('.container').firstChild);
    
      // Update scores and move to last active step
      setTimeout(() => {
        updateScores();
        if (formData.step > 1) {
          nextStep(formData.step);
        }
      }, 500);
    }
    
    function showSaveIndicator() {
      const indicator = document.getElementById('save-indicator');
      indicator.style.opacity = '1';
      setTimeout(() => { indicator.style.opacity = '0'; }, 2000);
    }
    
    function collectScores(className) {
      const scores = {};
      document.querySelectorAll('.' + className).forEach(input => {
        if (input.id) {
          scores[input.id] = input.value;
        }
      });
      return scores;
    }
    
    function restoreScores(scores, className) {
      if (!scores) return;
    
      Object.keys(scores).forEach(id => {
        const input = document.getElementById(id);
        if (input) {
          input.value = scores[id];
          if (input.className.includes(className)) {
            const rating = input.closest('.sub-criteria')?.querySelector('.star-rating');
            if (rating) {
              const stars = rating.querySelectorAll('span');
              highlightStars(stars, scores[id]);
            }
          }
        }
      });
    }
    
    function getActiveStepIndex() {
      const activeTab = document.querySelector('.nav-link.active');
      return activeTab ? parseInt(activeTab.id.replace('step', '').replace('-tab', '')) : 1;
    }
    
    function setFieldValue(id, value) {
      const field = document.getElementById(id);
      if (field && value) {
        field.value = value;
      }
    }
    
    // Add skill type help explanation
    function addSkillTypeHelp() {
      // Create help button and add to page
      const helpIcon = document.createElement('i');
      helpIcon.className = 'bi bi-question-circle text-info ms-2';
      helpIcon.style.cursor = 'pointer';
      helpIcon.title = 'View explanation of Hard vs Soft Skills classification';
      
      // Help content
      const helpContent = `
        <div class="modal fade" id="skillHelpModal" tabindex="-1" aria-hidden="true">
          <div class="modal-dialog">
            <div class="modal-content">
              <div class="modal-header">
                <h5 class="modal-title">Hard Skills vs Soft Skills Classification</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
              </div>
              <div class="modal-body">
                <h6>Hard Skills Assessment Items:</h6>
                <ul>
                  <li><strong>Financial Analyst:</strong> Financial modeling and valuation skills, due diligence and risk assessment, financial analysis and investment justification</li>
                  <li><strong>Research Analyst:</strong> Market and industry trend analysis, technology assessment and competitive landscape analysis, data analysis and research methods</li>
                  <li><strong>Operations Analyst:</strong> Business process analysis, KPI development and monitoring, project management and business operations</li>
                </ul>
                <h6>Soft Skills Assessment Items:</h6>
                <ul>
                  <li><strong>Financial Analyst:</strong> Communication with portfolio companies, investment proposal presentation, networking and relationship building</li>
                  <li><strong>Research Analyst:</strong> Critical thinking and insight, clear research findings presentation, learning agility for emerging trends</li>
                  <li><strong>Operations Analyst:</strong> Cross-functional collaboration, stakeholder management, adaptability and problem-solving</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      `;
      
      // Add to page
      const evalSteps = document.getElementById('evaluationSteps');
      if (evalSteps) {
        document.body.insertAdjacentHTML('beforeend', helpContent);
        const firstTab = evalSteps.querySelector('.nav-link');
        if (firstTab) {
          firstTab.insertAdjacentElement('beforeend', helpIcon);
          helpIcon.addEventListener('click', function(e) {
            e.preventDefault();
            new bootstrap.Modal(document.getElementById('skillHelpModal')).show();
          });
        }
      }
    }
  </script>
</body>
</html>
"""

    # Combine HTML parts
    complete_html = head_html + video_html + tail_html

    # Render HTML template with variables
    return render_template_string(complete_html,
                                  judge_role=judge_role,
                                  judge_name=judge_name,
                                  applicant=applicant)

# ========== Save Rating API ==========
# ========== Save Rating API ==========
@app.route('/api/save-rating', methods=['POST'])
def api_save_rating():
    data = request.get_json() or {}
    try:
        # Extract data from request
        judge_name = data.get('judge_name', '')
        judge_role = data.get('judge_role', '')
        evaluation_date_str = data.get('evaluation_date', '')
        applicant_name = data['applicant_name']
        applicant_id = data['applicant_id']
        applicant_university = data.get('applicant_university', '')
        applicant_email = data.get('applicant_email', '')
        applicant_role = data['applicant_role']
        resume_score = float(data['resume_score'])
        video_score = float(data['video_score'])
        final_score = float(data['final_score'])
        decision = data['decision']
        notes = data.get('notes', '')
        video_ratings = data.get('video_ratings', {})
        resume_ratings = data.get('resume_ratings', {})
        resume_ratings_json = json.dumps(resume_ratings, ensure_ascii=False)
        motivation_score = float(data.get('motivation_score', 0))

        # Parse date
        eval_date = None
        if evaluation_date_str:
            eval_date = datetime.strptime(evaluation_date_str, '%Y-%m-%d')
        else:
            eval_date = datetime.now()

        # JSON serialize video ratings
        video_ratings_json = json.dumps(video_ratings, ensure_ascii=False)

        # Check if this applicant already exists
        applicant = Applicant.query.filter_by(applicant_id=applicant_id).first()
        if not applicant:
            # Create new applicant
            applicant = Applicant(
                applicant_id=applicant_id,
                name=applicant_name,
                role=applicant_role,
                university=applicant_university,
                email=applicant_email,
                status='evaluated'
            )
            db.session.add(applicant)

        # Update applicant status based on decision
        applicant.status = decision.lower()

        # Create new evaluation
        new_eval = Evaluation(
            judge_name=judge_name,
            judge_role=judge_role,
            evaluation_date=eval_date,
            applicant_name=applicant_name,
            applicant_id=applicant_id,
            applicant_role=applicant_role,
            resume_score=resume_score,
            resume_ratings=resume_ratings_json,
            motivation_score=motivation_score,
            video_ratings=video_ratings_json,
            video_score=video_score,
            final_score=final_score,
            decision=decision,
            notes=notes
        )

        db.session.add(new_eval)
        db.session.commit()

        return jsonify({"evaluation_id": new_eval.id}), 200

    except KeyError as e:
        return jsonify({"error": f"Missing required field: {str(e)}"}), 400
    except ValueError as e:
        return jsonify({"error": f"Value error: {str(e)}"}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Save failed: {str(e)}"}), 500
    
# ========== View All Evaluation Records ==========
@app.route('/evaluations')
def view_evaluations():
    # Get filter parameters
    judge_role = request.args.get('judge_role', '')
    decision = request.args.get('decision', '')
    applicant_role = request.args.get('applicant_role', '')
    search_query = request.args.get('q', '')

    # Base query
    query = Evaluation.query

    # Apply filters
    if judge_role:
        query = query.filter_by(judge_role=judge_role)

    if decision:
        query = query.filter_by(decision=decision)

    if applicant_role:
        query = query.filter_by(applicant_role=applicant_role)

    if search_query:
        query = query.filter(
            (Evaluation.applicant_name.ilike(f'%{search_query}%')) |
            (Evaluation.applicant_id.ilike(f'%{search_query}%')) |
            (Evaluation.judge_name.ilike(f'%{search_query}%'))
        )

    # Sort by most recent
    evals = query.order_by(Evaluation.created_at.desc()).all()

    # Get unique values for filter dropdowns
    judge_roles = db.session.query(Evaluation.judge_role).distinct().all()
    decisions = db.session.query(Evaluation.decision).distinct().all()
    applicant_roles = db.session.query(Evaluation.applicant_role).distinct().all()
    
    # Get applicant info for all evaluations
    applicant_ids = [e.applicant_id for e in evals]
    applicants = Applicant.query.filter(Applicant.applicant_id.in_(applicant_ids)).all()
    applicant_info = {a.applicant_id: a for a in applicants}

    html = render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Evaluation Records - Sertie</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
  <style>
    body {
      background-color: #B3FFFA;
    }
    .container {
      max-width: 1200px;
      margin: 30px auto;
    }
    .filter-section {
      background-color: #fff;
      border-radius: 10px;
      padding: 20px;
      margin-bottom: 20px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }
    .table-container {
      background-color: #fff;
      border-radius: 10px;
      padding: 20px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.05);
      overflow: auto;
    }
    .table th {
      background-color: #f5f5f5;
    }
    .decision-badge {
      display: inline-block;
      padding: 5px 10px;
      border-radius: 20px;
      font-size: 0.75rem;
      font-weight: bold;
      text-transform: uppercase;
    }
    .decision-advance {
      background-color: #d4edda;
      color: #155724;
    }
    .decision-waitlist {
      background-color: #fff3cd;
      color: #856404;
    }
    .decision-reject {
      background-color: #f8d7da;
      color: #721c24;
    }
    .score-display {
      font-weight: bold;
      padding: 2px 8px;
      border-radius: 4px;
    }
    .score-high {
      background-color: #d4edda;
      color: #155724;
    }
    .score-mid {
      background-color: #fff3cd;
      color: #856404;
    }
    .score-low {
      background-color: #f8d7da;
      color: #721c24;
    }
    .action-buttons a {
      margin-right: 5px;
    }
    @media (max-width: 768px) {
      .filter-section {
        padding: 15px 10px;
      }
      .table-container {
        padding: 10px;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h1><i class="bi bi-list-check"></i> Evaluation Records</h1>
      <div>
        <a href="/rating" class="btn btn-success">
          <i class="bi bi-plus-circle"></i> New Evaluation
        </a>
        <button type="button" id="exportBtn" class="btn btn-outline-primary ms-2">
          <i class="bi bi-download"></i> Export Data
        </button>    
        <a href="/" class="btn btn-outline-secondary ms-2">
          <i class="bi bi-house"></i> Back to Home
        </a>
      </div>
    </div>

    <div class="filter-section">
      <form id="filter-form" method="get" class="row g-3">
        <div class="col-md-3">
          <label for="search" class="form-label">Search:</label>
          <input type="text" class="form-control" id="search" name="q"
                 placeholder="Name, ID, or evaluator..." value="{{ request.args.get('q', '') }}">
        </div>
        <div class="col-md-2">
          <label for="judge_role" class="form-label">Evaluator Role:</label>
          <select class="form-select" id="judge_role" name="judge_role">
            <option value="">All Roles</option>
            {% for role in judge_roles %}
            <option value="{{ role[0] }}"
                    {% if request.args.get('judge_role') == role[0] %}selected{% endif %}>
              {{ role[0]|capitalize }}
            </option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-2">
          <label for="decision" class="form-label">Decision:</label>
          <select class="form-select" id="decision" name="decision">
            <option value="">All Decisions</option>
            {% for d in decisions %}
            <option value="{{ d[0] }}"
                    {% if request.args.get('decision') == d[0] %}selected{% endif %}>
              {{ d[0]|capitalize }}
            </option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-3">
          <label for="applicant_role" class="form-label">Applied Position:</label>
          <select class="form-select" id="applicant_role" name="applicant_role">
            <option value="">All Positions</option>
            {% for role in applicant_roles %}
            <option value="{{ role[0] }}"
                    {% if request.args.get('applicant_role') == role[0] %}selected{% endif %}>
              {{ role[0]|replace('-', ' ')|capitalize }}
            </option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-2 d-flex align-items-end">
          <div class="d-grid gap-2 w-100">
            <button type="submit" class="btn btn-primary">
              <i class="bi bi-funnel"></i> Filter
            </button>
            <a href="/evaluations" class="btn btn-outline-secondary">
              <i class="bi bi-x-circle"></i> Clear
            </a>
          </div>
        </div>
      </form>
    </div>

    <div class="table-container">
      {% if evals %}
      <div class="table-responsive">
        <table class="table table-hover">
          <thead>
            <tr>
              <th>ID</th>
              <th>Applicant</th>
              <th>Evaluator</th>
              <th>Resume</th>
              <th>Video</th>
              <th>Total</th>
              <th>Decision</th>
              <th>Date</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {% for e in evals %}
            <tr>
              <td>{{ e.id }}</td>
              <td>
                <strong>{{ e.applicant_name }}</strong><br>
                <small class="text-muted">ID: {{ e.applicant_id }}</small>
                {% if e.applicant_id in applicant_info %}
                  <br><small class="text-muted">
                    {% if applicant_info[e.applicant_id].university %}
                      <i class="bi bi-building"></i> {{ applicant_info[e.applicant_id].university }}
                    {% endif %}
                    {% if applicant_info[e.applicant_id].email %}
                      <br><i class="bi bi-envelope"></i> {{ applicant_info[e.applicant_id].email }}
                    {% endif %}
                  </small>
                {% endif %}
                <br><small>{{ e.applicant_role|replace('-', ' ')|capitalize }}</small>
              </td>
              <td>
                {{ e.judge_name }}<br>
                <small class="text-muted">{{ e.judge_role|capitalize }}</small>
              </td>
              <td>
                <span class="score-display
                  {% if e.resume_score >= 4.0 %}score-high
                  {% elif e.resume_score >= 3.0 %}score-mid
                  {% else %}score-low{% endif %}">
                  {{ "%.1f"|format(e.resume_score) }}
                </span>
              </td>
              <td>
                <span class="score-display
                  {% if e.video_score >= 4.0 %}score-high
                  {% elif e.video_score >= 3.0 %}score-mid
                  {% else %}score-low{% endif %}">
                  {{ "%.1f"|format(e.video_score) }}
                </span>
              </td>
              <td>
                <span class="score-display
                  {% if e.final_score >= 4.0 %}score-high
                  {% elif e.final_score >= 3.0 %}score-mid
                  {% else %}score-low{% endif %}">
                  {{ "%.1f"|format(e.final_score) }}
                </span>
              </td>
              <td>
                <span class="decision-badge decision-{{ e.decision|lower }}">
                  {{ e.decision }}
                </span>
              </td>
              <td>{{ e.evaluation_date.strftime("%Y-%m-%d") }}</td>
              <td class="action-buttons">
                <a href="/evaluation/{{ e.id }}" class="btn btn-sm btn-outline-primary"
                   title="View Details">
                  <i class="bi bi-eye"></i>
                </a>
                <a href="/combined-score?id={{ e.applicant_id }}" class="btn btn-sm btn-outline-info"
                   title="Combined Score">
                  <i class="bi bi-bar-chart"></i>
                </a>
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      <div class="mt-3">
        <p class="text-muted">Showing {{ evals|length }} records</p>
      </div>
      {% else %}
      <div class="text-center py-5">
        <i class="bi bi-search" style="font-size: 3rem; color: #adb5bd;"></i>
        <h4 class="mt-3">No evaluation records found</h4>
        <p class="text-muted">Please adjust your filter criteria or create a new evaluation.</p>
        <a href="/rating" class="btn btn-primary mt-2">
          <i class="bi bi-plus-circle"></i> New Evaluation
        </a>
      </div>
      {% endif %}
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
  
  <script>
    document.addEventListener('DOMContentLoaded', function() {
      // Find the export button
      const exportBtn = document.getElementById('exportBtn');
      
      if (exportBtn) {
        // Add click event handler
        exportBtn.addEventListener('click', function() {
          // Show loading state
          exportBtn.disabled = true;
          exportBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Exporting...';
          
          // Make fetch request to export API
          fetch('/api/export-evaluations')
            .then(response => {
              // Check if response is OK
              if (!response.ok) {
                throw new Error('Export failed, status code: ' + response.status);
              }
              
              // Get filename from Content-Disposition header if available
              let filename = 'evaluations.csv';
              const contentDisposition = response.headers.get('Content-Disposition');
              if (contentDisposition) {
                const filenameMatch = contentDisposition.match(/filename="(.+?)"/);
                if (filenameMatch && filenameMatch[1]) {
                  filename = filenameMatch[1];
                }
              }
              
              // Convert response to blob
              return response.blob().then(blob => {
                // Create download link
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                a.download = filename;
                
                // Append to body, trigger click, then remove
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                
                // Reset button state
                exportBtn.disabled = false;
                exportBtn.innerHTML = '<i class="bi bi-download"></i> Export Data';
              });
            })
            .catch(error => {
              // Reset button state
              exportBtn.disabled = false;
              exportBtn.innerHTML = '<i class="bi bi-download"></i> Export Data';
              
              // Show error
              alert('Export failed: ' + error.message);
              console.error('Export error:', error);
            });
        });
      }
    });
  </script>
</body>
</html>

""", evals=evals, judge_roles=judge_roles, decisions=decisions, applicant_roles=applicant_roles, request=request, applicant_info=applicant_info)

    return html


@app.route('/combined-score')
def combined_score():
    # 获取申请人ID
    applicant_id = request.args.get('id', '')

    if not applicant_id:
        # 显示所有申请人
        all_applicants = db.session.query(
            Evaluation.applicant_name,
            Evaluation.applicant_id,
            Evaluation.applicant_role
        ).distinct().all()

        html = render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Combined Score Query</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
  <style>
    body {
      background-color: #B3FFFA;
    }
    .container {
      max-width: 900px;
      margin: 30px auto;
    }
    .list-container {
      background-color: #fff;
      border-radius: 10px;
      padding: 20px;
      box-shadow: 0 2px 15px rgba(0,0,0,0.1);
    }
    .list-group-item {
      transition: transform 0.2s, box-shadow 0.2s;
      border-left: 3px solid #009688;
    }
    .list-group-item:hover {
      transform: translateY(-2px);
      box-shadow: 0 5px 10px rgba(0,0,0,0.1);
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h1><i class="bi bi-calculator"></i> Combined Score Query</h1>
      <a href="/" class="btn btn-outline-secondary">
        <i class="bi bi-arrow-left"></i> Back to Home
      </a>
    </div>

    <div class="mb-4">
      <div class="input-group">
        <input type="text" class="form-control" id="searchInput"
               placeholder="Search applicant name or ID...">
        <button class="btn btn-outline-secondary" type="button">
          <i class="bi bi-search"></i>
        </button>
      </div>
    </div>

    <div class="list-container">
      <h4 class="mb-4">Select Applicant to View Combined Score</h4>

      <div class="list-group" id="applicantListGroup">
        {% for an, aid, role in apps %}
        <a href="/combined-score?id={{ aid }}" class="list-group-item list-group-item-action">
          <div class="d-flex w-100 justify-content-between align-items-center">
            <div>
              <h5 class="mb-1">{{ an }}</h5>
              <p class="mb-1 text-muted">ID: {{ aid }} | Position: {{ role|replace('-', ' ')|capitalize }}</p>
            </div>
            <i class="bi bi-chevron-right"></i>
          </div>
        </a>
        {% else %}
        <div class="text-center py-4">
          <p class="text-muted">No applicants found.</p>
        </div>
        {% endfor %}
      </div>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
  <script>
    // Search functionality
    document.getElementById('searchInput').addEventListener('keyup', function() {
      const searchText = this.value.toLowerCase();
      const items = document.querySelectorAll('#applicantListGroup .list-group-item');

      items.forEach(item => {
        const text = item.textContent.toLowerCase();
        if (text.includes(searchText)) {
          item.style.display = '';
        } else {
          item.style.display = 'none';
        }
      });
    });
  </script>
</body>
</html>
""", apps=all_applicants)

        return html

    # 调试信息
    print(f"Looking for applicant ID: '{applicant_id}'")
    all_evals = Evaluation.query.all()
    print(f"Total evaluations in system: {len(all_evals)}")
    print(f"All applicant IDs: {[e.applicant_id for e in all_evals]}")

    # 根据指定ID获取所有评价记录
    records = Evaluation.query.filter(
        (Evaluation.applicant_id == applicant_id) | 
        (Evaluation.applicant_id == str(applicant_id))
    ).all()
    
    if not records:
        # 尝试查找可能相关的记录
        possible_matches = Evaluation.query.filter(
            Evaluation.applicant_id.like(f"%{applicant_id}%")
        ).all()
        
        if possible_matches:
            potential_ids = set([e.applicant_id for e in possible_matches])
            return f"""<h3>No exact records found for ID={applicant_id}</h3>
                    <p>Similar IDs found: {', '.join(potential_ids)}</p>
                    <p><a href="/evaluations">Return to evaluations list</a></p>"""
        else:
            return f"""<h3>No records found for ID={applicant_id}</h3>
                    <p>Please verify the applicant ID is correct.</p>
                    <p><a href="/evaluations">Return to evaluations list</a></p>"""

    # 按评委角色分组（这里对 judge_role 做小写处理）
    ceo_eval = None
    intern1_eval = None
    intern2_eval = None

    for r in records:
        role = r.judge_role.lower() if r.judge_role else ''
        if role == 'ceo':
            ceo_eval = r
        elif role == 'intern1':
            intern1_eval = r
        elif role == 'intern2':
            intern2_eval = r

    # 根据可用评价计算加权和
    available_evaluations = 0
    weighted_sum = 0
    
    if ceo_eval:
        weighted_sum += ceo_eval.final_score * 0.5
        available_evaluations += 0.5
        
    if intern1_eval:
        weighted_sum += intern1_eval.final_score * 0.25
        available_evaluations += 0.25
        
    if intern2_eval:
        weighted_sum += intern2_eval.final_score * 0.25
        available_evaluations += 0.25
    
    # 归一化计算 combined score
    combined_score = weighted_sum / available_evaluations if available_evaluations > 0 else 0

    # 获取申请人信息
    applicant_name = records[0].applicant_name
    applicant_role = records[0].applicant_role

    html = render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Combined Score - {{ applicant_name }}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
  <style>
    body {
      background-color: #B3FFFA;
      font-family: Arial, sans-serif;
    }
    .container {
      max-width: 900px;
      margin: 30px auto;
      background-color: #fff;
      border-radius: 10px;
      box-shadow: 0 0 20px rgba(0,0,0,0.1);
      padding: 25px;
    }
    .score-card {
      margin-bottom: 20px;
      border-radius: 8px;
      background-color: #f8f9fa;
      padding: 15px;
    }
    .score-value {
      font-size: 2.5rem;
      font-weight: bold;
      color: #198754;
      text-align: center;
    }
    .score-label {
      text-align: center;
      color: #6c757d;
      margin-bottom: 15px;
    }
    .score-item {
      padding: 10px;
      margin-bottom: 10px;
      border-radius: 5px;
      background-color: #fff;
    }
    .score-item .label {
      font-weight: bold;
    }
    .score-item .value {
      float: right;
      font-weight: bold;
    }
    .high {
      color: #198754;
    }
    .medium {
      color: #fd7e14;
    }
    .low {
      color: #dc3545;
    }
    .weight-bar {
      height: 8px;
      background-color: #e9ecef;
      margin-top: 5px;
      border-radius: 4px;
      overflow: hidden;
      display: flex;
    }
    .weight-segment {
      height: 100%;
    }
    .weight-ceo {
      background-color: #0d6efd;
      width: 50%;
    }
    .weight-intern1 {
      background-color: #6610f2;
      width: 25%;
    }
    .weight-intern2 {
      background-color: #d63384;
      width: 25%;
    }
  </style>
</head>
<body>
  <div class="container">
    <h1 class="text-center text-success mb-4">{{ applicant_name }}'s Combined Score</h1>
    <p class="text-center text-muted mb-4">ID: {{ applicant_id }} | Position: {{ applicant_role|replace('-', ' ')|capitalize }}</p>

    <div class="d-flex justify-content-between mb-4">
      <a href="/combined-score" class="btn btn-outline-secondary">← Back to List</a>
      <a href="/" class="btn btn-outline-primary">Back to Home</a>
    </div>

    <!-- Combined Score Display -->
    <div class="score-card">
      <div class="score-label">Combined Score (Weighted)</div>
      <div class="score-value">{{ "%.2f"|format(combined_score) }}</div>
      <div class="text-center text-muted mb-3">
        {% if available_evaluations < 1 %}
          Based on {{ (available_evaluations * 100)|int }}% of total evaluations
        {% else %}
          CEO (50%) + Intern1 (25%) + Intern2 (25%)
        {% endif %}
      </div>

      <!-- Weight Bar Visualization -->
      <div class="weight-bar">
        {% if ceo_eval %}
        <div class="weight-segment weight-ceo" title="CEO: 50%"></div>
        {% endif %}
        {% if intern1_eval %}
        <div class="weight-segment weight-intern1" title="Intern1: 25%"></div>
        {% endif %}
        {% if intern2_eval %}
        <div class="weight-segment weight-intern2" title="Intern2: 25%"></div>
        {% endif %}
      </div>
    </div>

    <!-- Individual Evaluator Scores -->
    <div class="row">
      <!-- CEO Evaluation -->
      <div class="col-md-4 mb-3">
        <div class="card">
          <div class="card-header bg-primary text-white">
            CEO Evaluation (50%)
          </div>
          <div class="card-body">
            {% if ceo_eval %}
              <div class="score-item">
                <span class="label">Resume:</span>
                <span class="value {{ 'high' if ceo_eval.resume_score >= 4 else 'medium' if ceo_eval.resume_score >= 3 else 'low' }}">
                  {{ "%.1f"|format(ceo_eval.resume_score) }}
                </span>
              </div>
              <div class="score-item">
                <span class="label">Video:</span>
                <span class="value {{ 'high' if ceo_eval.video_score >= 4 else 'medium' if ceo_eval.video_score >= 3 else 'low' }}">
                  {{ "%.1f"|format(ceo_eval.video_score) }}
                </span>
              </div>
              <div class="score-item">
                  <span class="label">Motivation:</span>
                  <span class="value {{ 'high' if ceo_eval.motivation_score >= 4 else 'medium' if ceo_eval.motivation_score >= 3 else 'low' }}">
                    {{ "%.1f"|format(ceo_eval.motivation_score) }}
                  </span>
              </div>
              <div class="score-item">
                <span class="label">Final:</span>
                <span class="value {{ 'high' if ceo_eval.final_score >= 4 else 'medium' if ceo_eval.final_score >= 3 else 'low' }}">
                  {{ "%.1f"|format(ceo_eval.final_score) }}
                </span>
              </div>
              <div class="score-item">
                <span class="label">Decision:</span>
                <span class="badge {{ 'bg-success' if ceo_eval.decision == 'advance' else 'bg-warning' if ceo_eval.decision == 'waitlist' else 'bg-danger' }}">
                  {{ ceo_eval.decision|capitalize }}
                </span>
              </div>
              {% if ceo_eval.notes %}
              <div class="mt-3">
                <strong>Notes:</strong>
                <p class="mt-2">{{ ceo_eval.notes }}</p>
              </div>
              {% endif %}
            {% else %}
              <div class="text-center text-muted py-4">
                No CEO evaluation
              </div>
            {% endif %}
          </div>
        </div>
      </div>

      <!-- Intern1 Evaluation -->
      <div class="col-md-4 mb-3">
        <div class="card">
          <div class="card-header bg-info text-white">
            Intern1 Evaluation (25%)
          </div>
          <div class="card-body">
            {% if intern1_eval %}
              <div class="score-item">
                <span class="label">Resume:</span>
                <span class="value {{ 'high' if intern1_eval.resume_score >= 4 else 'medium' if intern1_eval.resume_score >= 3 else 'low' }}">
                  {{ "%.1f"|format(intern1_eval.resume_score) }}
                </span>
              </div>
              <div class="score-item">
                <span class="label">Video:</span>
                <span class="value {{ 'high' if intern1_eval.video_score >= 4 else 'medium' if intern1_eval.video_score >= 3 else 'low' }}">
                  {{ "%.1f"|format(intern1_eval.video_score) }}
                </span>
              </div>
              <div class="score-item">
                  <span class="label">Motivation:</span>
                  <span class="value {{ 'high' if intern1_eval.motivation_score >= 4 else 'medium' if intern1_eval.motivation_score >= 3 else 'low' }}">
                    {{ "%.1f"|format(intern1_eval.motivation_score) }}
                  </span>
              </div>
              <div class="score-item">
                <span class="label">Final:</span>
                <span class="value {{ 'high' if intern1_eval.final_score >= 4 else 'medium' if intern1_eval.final_score >= 3 else 'low' }}">
                  {{ "%.1f"|format(intern1_eval.final_score) }}
                </span>
              </div>
              <div class="score-item">
                <span class="label">Decision:</span>
                <span class="badge {{ 'bg-success' if intern1_eval.decision == 'advance' else 'bg-warning' if intern1_eval.decision == 'waitlist' else 'bg-danger' }}">
                  {{ intern1_eval.decision|capitalize }}
                </span>
              </div>
              {% if intern1_eval.notes %}
              <div class="mt-3">
                <strong>Notes:</strong>
                <p class="mt-2">{{ intern1_eval.notes }}</p>
              </div>
              {% endif %}
            {% else %}
              <div class="text-center text-muted py-4">
                No Intern1 evaluation
              </div>
            {% endif %}
          </div>
        </div>
      </div>

      <!-- Intern2 Evaluation -->
      <div class="col-md-4 mb-3">
        <div class="card">
          <div class="card-header bg-warning text-dark">
            Intern2 Evaluation (25%)
          </div>
          <div class="card-body">
            {% if intern2_eval %}
              <div class="score-item">
                <span class="label">Resume:</span>
                <span class="value {{ 'high' if intern2_eval.resume_score >= 4 else 'medium' if intern2_eval.resume_score >= 3 else 'low' }}">
                  {{ "%.1f"|format(intern2_eval.resume_score) }}
                </span>
              </div>
              <div class="score-item">
                <span class="label">Video:</span>
                <span class="value {{ 'high' if intern2_eval.video_score >= 4 else 'medium' if intern2_eval.video_score >= 3 else 'low' }}">
                  {{ "%.1f"|format(intern2_eval.video_score) }}
                </span>
              </div>
              <div class="score-item">
                  <span class="label">Motivation:</span>
                  <span class="value {{ 'high' if intern2_eval.motivation_score >= 4 else 'medium' if intern2_eval.motivation_score >= 3 else 'low' }}">
                    {{ "%.1f"|format(intern2_eval.motivation_score) }}
                  </span>
              </div>
              <div class="score-item">
                <span class="label">Final:</span>
                <span class="value {{ 'high' if intern2_eval.final_score >= 4 else 'medium' if intern2_eval.final_score >= 3 else 'low' }}">
                  {{ "%.1f"|format(intern2_eval.final_score) }}
                </span>
              </div>
              <div class="score-item">
                <span class="label">Decision:</span>
                <span class="badge {{ 'bg-success' if intern2_eval.decision == 'advance' else 'bg-warning' if intern2_eval.decision == 'waitlist' else 'bg-danger' }}">
                  {{ intern2_eval.decision|capitalize }}
                </span>
              </div>
              {% if intern2_eval.notes %}
              <div class="mt-3">
                <strong>Notes:</strong>
                <p class="mt-2">{{ intern2_eval.notes }}</p>
              </div>
              {% endif %}
            {% else %}
              <div class="text-center text-muted py-4">
                No Intern2 evaluation
              </div>
            {% endif %}
          </div>
        </div>
      </div>
    </div>

    <!-- Final Decision Buttons -->
    <div class="mt-4 text-center">
      <div class="btn-group">
        <a href="/applicant/{{ applicant_id }}/advance" class="btn btn-success btn-lg">
          <i class="bi bi-check-circle"></i> Advance
        </a>
        <a href="/applicant/{{ applicant_id }}/waitlist" class="btn btn-warning btn-lg">
          <i class="bi bi-hourglass-split"></i> Waitlist
        </a>
        <a href="/applicant/{{ applicant_id }}/reject" class="btn btn-danger btn-lg">
          <i class="bi bi-x-circle"></i> Reject
        </a>
      </div>
    </div>
  </div>
</body>
</html>
""", applicant_id=applicant_id, applicant_name=applicant_name, applicant_role=applicant_role,
       combined_score=combined_score, ceo_eval=ceo_eval, intern1_eval=intern1_eval, intern2_eval=intern2_eval,
       available_evaluations=available_evaluations)

    return html

@app.route('/debug-applicant/<applicant_id>')
def debug_applicant(applicant_id):
    # Check database for all evaluation records
    all_evals = Evaluation.query.all()
    
    # Query with multiple approaches
    exact_matches = Evaluation.query.filter_by(applicant_id=applicant_id).all()
    string_matches = Evaluation.query.filter_by(applicant_id=str(applicant_id)).all()
    like_matches = Evaluation.query.filter(Evaluation.applicant_id.like(f"%{applicant_id}%")).all()
    
    output = f"""
    <h2>Debug Information for Applicant ID: {applicant_id}</h2>
    <p>Total evaluations in database: {len(all_evals)}</p>
    <p>Exact matches found: {len(exact_matches)}</p>
    <p>String matches found: {len(string_matches)}</p>
    <p>Partial matches found: {len(like_matches)}</p>
    
    <h3>All Applicant IDs in System:</h3>
    <ul>
    """
    
    for eval in all_evals:
        output += f"<li>ID: '{eval.applicant_id}' (Type: {type(eval.applicant_id).__name__}) - Judge: {eval.judge_role}, Score: {eval.final_score}</li>"
    
    output += "</ul>"
    
    if exact_matches or string_matches or like_matches:
        output += "<h3>Matching Records:</h3><ul>"
        
        for e in (exact_matches + string_matches + like_matches):
            if e not in exact_matches:
                output += f"<li>ID: '{e.applicant_id}' - Judge: {e.judge_role} (NON-EXACT MATCH)</li>"
            else:
                output += f"<li>ID: '{e.applicant_id}' - Judge: {e.judge_role}</li>"
                
        output += "</ul>"
    
    return output


# API Route: Export Evaluations as CSV
@app.route('/api/export-evaluations')
def export_evaluations():
    try:
        # Get all evaluation records
        evals = Evaluation.query.order_by(Evaluation.created_at.desc()).all()

        # Get applicant information for each evaluation record
        applicant_ids = [e.applicant_id for e in evals]
        applicants = {}
        try:
            applicant_records = Applicant.query.filter(Applicant.applicant_id.in_(applicant_ids)).all()
            for app in applicant_records:
                applicants[app.applicant_id] = app
        except:
            # Handle gracefully if Applicant table doesn't exist or query fails
            pass

        # Set response headers for proper encoding and file download
        headers = {
            'Content-Type': 'text/csv; charset=utf-8',
            'Content-Disposition': f'attachment; filename="sertie_evaluations_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        }
        
        # Add BOM for Excel compatibility with UTF-8
        csv_data = "\ufeff"
        
        # Define headers
        headers_row = [
            "ID", "Judge Name", "Judge Role", "Evaluation Date", 
            "Applicant Name", "Applicant ID", "Position", "University", "Email",
            "Resume Score", "Video Score", "Motivation Score", "Final Score", 
            "Decision", "Position Weight (Hard/Soft Skills)", "Notes"
        ]
        
        csv_data += ",".join(headers_row) + "\n"
        
        # Process each evaluation record
        for e in evals:
            # Get applicant information
            applicant = applicants.get(e.applicant_id, None)
            university = getattr(applicant, 'university', '') if applicant else ''
            email = getattr(applicant, 'email', '') if applicant else ''
            
            # Format date
            eval_date = e.evaluation_date.strftime('%Y-%m-%d') if e.evaluation_date else ""
            
            # Get position weights
            position = e.applicant_role
            weights = get_role_weights_for_export(position)
            weight_distribution = f"Hard {int(weights['hard'] * 100)}% / Soft {int(weights['soft'] * 100)}%"
            
            # Clean and escape notes
            notes = e.notes or ""
            notes = notes.replace('\n', ' ').replace('\r', ' ')
            
            # Prepare row data with proper CSV escaping
            row_data = [
                escape_csv_field(str(e.id)),
                escape_csv_field(e.judge_name),
                escape_csv_field(e.judge_role),
                escape_csv_field(eval_date),
                escape_csv_field(e.applicant_name),
                escape_csv_field(e.applicant_id),
                escape_csv_field(get_position_name_english(e.applicant_role)),
                escape_csv_field(university),
                escape_csv_field(email),
                format_float(e.resume_score),
                format_float(e.video_score),
                format_float(e.motivation_score),
                format_float(e.final_score),
                escape_csv_field(e.decision),
                escape_csv_field(weight_distribution),
                escape_csv_field(notes)
            ]
            
            csv_data += ",".join(row_data) + "\n"
            
        return csv_data, 200, headers
        
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        return jsonify({
            "error": f"Export failed: {str(e)}",
            "details": error_traceback
        }), 500

# Helper function for CSV field escaping
def escape_csv_field(value):
    """Properly escape a value for CSV inclusion"""
    if value is None:
        return '""'
    
    value = str(value)
    if ',' in value or '"' in value or '\n' in value or '\r' in value:
        # Escape quotes by doubling them and wrap in quotes
        return '"' + value.replace('"', '""') + '"'
    return value

# ========== View Individual Evaluation ==========
@app.route('/evaluation/<int:eval_id>')
def view_evaluation(eval_id):
    # Get the evaluation record
    evaluation = Evaluation.query.get_or_404(eval_id)
    
    # Try to get applicant info
    applicant = None
    try:
        applicant = Applicant.query.filter_by(applicant_id=evaluation.applicant_id).first()
    except:
        pass
    
    # Parse ratings JSON
    resume_ratings = {}
    video_ratings = {}
    
    try:
        if evaluation.resume_ratings:
            resume_ratings = json.loads(evaluation.resume_ratings)
    except:
        pass
        
    try:
        if evaluation.video_ratings:
            video_ratings = json.loads(evaluation.video_ratings)
    except:
        pass
    
    html = render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Evaluation Details - {{ evaluation.id }}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
  <style>
    body {
      background-color: #B3FFFA;
    }
    .container {
      max-width: 900px;
      margin: 30px auto;
      background-color: #fff;
      border-radius: 10px;
      box-shadow: 0 0 20px rgba(0,0,0,0.1);
      padding: 25px;
    }
    .section-title {
      border-bottom: 2px solid #eee;
      padding-bottom: 10px;
      margin-bottom: 20px;
      color: #009688;
    }
    .info-card {
      background-color: #f8f9fa;
      border-radius: 8px;
      padding: 15px;
      margin-bottom: 20px;
    }
    .info-item {
      margin-bottom: 10px;
    }
    .info-label {
      font-weight: bold;
      color: #555;
    }
    .score-card {
      background-color: #f8f9fa;
      border-radius: 8px;
      padding: 15px;
      margin-bottom: 20px;
    }
    .score-item {
      display: flex;
      justify-content: space-between;
      margin-bottom: 10px;
      padding: 8px 0;
      border-bottom: 1px dashed #ddd;
    }
    .score-item:last-child {
      border-bottom: none;
    }
    .star-display {
      color: #FFC107;
    }
    .decision {
      display: inline-block;
      padding: 5px 15px;
      border-radius: 20px;
      font-weight: bold;
      text-transform: uppercase;
    }
    .decision-advance {
      background-color: #d4edda;
      color: #155724;
    }
    .decision-waitlist {
      background-color: #fff3cd;
      color: #856404;
    }
    .decision-reject {
      background-color: #f8d7da;
      color: #721c24;
    }
    .final-score {
      font-size: 2.5rem;
      font-weight: bold;
      text-align: center;
      color: #009688;
      margin: 20px 0;
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h1><i class="bi bi-file-earmark-text"></i> Evaluation Details</h1>
      <div>
        <a href="/evaluations" class="btn btn-outline-secondary">
          <i class="bi bi-arrow-left"></i> Back to List
        </a>
        <a href="/combined-score?id={{ evaluation.applicant_id }}" class="btn btn-outline-primary">
          <i class="bi bi-bar-chart"></i> Combined Score
        </a>
      </div>
    </div>

    <!-- Basic Information -->
    <div class="row">
      <div class="col-md-6">
        <h3 class="section-title">Applicant Information</h3>
        <div class="info-card">
          <div class="info-item">
            <span class="info-label">Name:</span>
            <span>{{ evaluation.applicant_name }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">ID:</span>
            <span>{{ evaluation.applicant_id }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">Position:</span>
            <span>{{ evaluation.applicant_role|replace('-', ' ')|capitalize }}</span>
          </div>
          {% if applicant %}
          <div class="info-item">
            <span class="info-label">University:</span>
            <span>{{ applicant.university or 'N/A' }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">Email:</span>
            <span>{{ applicant.email or 'N/A' }}</span>
          </div>
          {% endif %}
        </div>
      </div>

      <div class="col-md-6">
        <h3 class="section-title">Evaluation Information</h3>
        <div class="info-card">
          <div class="info-item">
            <span class="info-label">Evaluator:</span>
            <span>{{ evaluation.judge_name }} ({{ evaluation.judge_role|capitalize }})</span>
          </div>
          <div class="info-item">
            <span class="info-label">Date:</span>
            <span>{{ evaluation.evaluation_date.strftime('%Y-%m-%d') }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">Decision:</span>
            <span class="decision decision-{{ evaluation.decision }}">{{ evaluation.decision|capitalize }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Scores Overview -->
    <h3 class="section-title">Scores Overview</h3>
    <div class="final-score">
      <i class="bi bi-award"></i> Final Score: {{ "%.1f"|format(evaluation.final_score) }}
      <div class="text-muted fs-6">Resume (40%) + Video (50%) + Motivation (10%)</div>
    </div>

    <div class="row mb-4">
      <div class="col-md-4">
        <div class="card text-center">
          <div class="card-header bg-light">Resume Score</div>
          <div class="card-body">
            <h5 class="card-title">{{ "%.1f"|format(evaluation.resume_score) }} / 5.0</h5>
          </div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="card text-center">
          <div class="card-header bg-light">Video Score</div>
          <div class="card-body">
            <h5 class="card-title">{{ "%.1f"|format(evaluation.video_score) }} / 5.0</h5>
          </div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="card text-center">
          <div class="card-header bg-light">Motivation Score</div>
          <div class="card-body">
            <h5 class="card-title">{{ "%.1f"|format(evaluation.motivation_score) }} / 5.0</h5>
          </div>
        </div>
      </div>
    </div>

    <!-- Detailed Scores -->
    <div class="row">
      <!-- Resume Ratings -->
      <div class="col-md-6">
        <h3 class="section-title">Resume Evaluation Details</h3>
        <div class="score-card">
          {% if resume_ratings %}
            {% for key, value in resume_ratings.items() %}
            <div class="score-item">
              <span>{{ key|replace('_', ' ')|capitalize }}</span>
              <span class="star-display">
                {% set score = value.score if value is mapping else value %}
                {% for i in range(score|int) %}★{% endfor %}
                {% if score|int < score %}½{% endif %}
                ({{ score }})
              </span>
            </div>
            {% endfor %}
          {% else %}
            <p class="text-muted text-center">No detailed resume ratings available</p>
          {% endif %}
        </div>
      </div>

      <!-- Video Ratings -->
      <div class="col-md-6">
        <h3 class="section-title">Video Evaluation Details</h3>
        <div class="score-card">
          {% if video_ratings %}
            {% for key, value in video_ratings.items() %}
            <div class="score-item">
              <span>{{ key|replace('_', ' ')|capitalize }}</span>
              <span class="star-display">
                {% set score = value.score if value is mapping else value %}
                {% for i in range(score|int) %}★{% endfor %}
                {% if score|int < score %}½{% endif %}
                ({{ score }})
              </span>
            </div>
            {% endfor %}
          {% else %}
            <p class="text-muted text-center">No detailed video ratings available</p>
          {% endif %}
        </div>
      </div>
    </div>

    <!-- Notes -->
    {% if evaluation.notes %}
    <h3 class="section-title">Notes & Feedback</h3>
    <div class="card mb-4">
      <div class="card-body">
        <p>{{ evaluation.notes|nl2br }}</p>
      </div>
    </div>
    {% endif %}

  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
""", evaluation=evaluation, applicant=applicant, resume_ratings=resume_ratings, video_ratings=video_ratings)

    return html



# ========== Applicant Status Update Routes ==========
@app.route('/applicant/<applicant_id>/<action>')
def update_applicant_status(applicant_id, action):
    if action not in ['advance', 'waitlist', 'reject']:
        return "Invalid action", 400
        
    try:
        # Find the applicant
        applicant = Applicant.query.filter_by(applicant_id=applicant_id).first()
        
        if not applicant:
            return f"Applicant with ID {applicant_id} not found", 404
            
        # Update status
        applicant.status = action
        db.session.commit()
        
        # Create a new evaluation for CEO (if not exists)
        existing_ceo_eval = Evaluation.query.filter_by(
            applicant_id=applicant_id, 
            judge_role='ceo'
        ).first()
        
        if not existing_ceo_eval:
            # Calculate final score as average of existing evaluations
            evals = Evaluation.query.filter_by(applicant_id=applicant_id).all()
            avg_score = sum(e.final_score for e in evals) / len(evals) if evals else 0
            
            # Create CEO consensus evaluation
            new_eval = Evaluation(
                judge_name="Consensus Decision",
                judge_role="ceo",
                evaluation_date=datetime.now(),
                applicant_name=applicant.name if applicant else "Unknown",
                applicant_id=applicant_id,
                applicant_role=applicant.role if applicant else "Unknown",
                resume_score=avg_score,
                video_score=avg_score,
                motivation_score=avg_score,
                final_score=avg_score,
                decision=action,
                notes=f"Consensus decision made through combined score interface on {datetime.now().strftime('%Y-%m-%d')}."
            )
            
            db.session.add(new_eval)
            db.session.commit()
        
        # Redirect to combined score page
        return redirect(f"/combined-score?id={applicant_id}")
        
    except Exception as e:
        db.session.rollback()
        return f"Error updating applicant status: {str(e)}", 500
    
# ========== Main Execution ==========
if __name__ == '__main__':
    app.run(debug=True)