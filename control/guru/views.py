import os
import random
from datetime import datetime
from .decorators import admin_required
from bson import ObjectId
from django.conf import settings
from django.contrib.auth import authenticate, login as auth_login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from pymongo import MongoClient

# MongoDB setup
client = MongoClient("mongodb://localhost:27017/")
db = client.mindmate_db
questions_collection = db.questions  # Assuming your collection is named 'questions'

def index(request):
    return render(request, 'index.html')

def fetch_questions_from_db():
    categories = questions_collection.find({}, {"_id": 0, "category": 1, "questions": 1})
    questions_db = {}
    for category in categories:
        if "category" in category and "questions" in category:
            questions_db[category["category"]] = category["questions"]
        else:
            print(f"Skipping document due to missing fields: {category}")
    return questions_db

import random

import random

def select_random_questions(username, questions_db, session_questions, num_questions_per_category=7):
    selected_questions = {}
    
    for category, questions in questions_db.items():
        # Filter out previously asked questions for this session
        available_questions = [q for q in questions if q not in session_questions]

        if len(available_questions) >= num_questions_per_category:
            # If enough new questions are available, select randomly
            selected_questions[category] = random.sample(available_questions, num_questions_per_category)
        else:
            # If not enough new questions, reuse previously asked questions
            print(f"Not enough new questions in category '{category}'. Reusing previously asked questions.")
            selected_questions[category] = random.sample(questions, min(num_questions_per_category, len(questions)))
        
        # Update the session questions
        session_questions.update(selected_questions[category])
    
    return selected_questions

@login_required
def assessment(request):
    today = timezone.now().strftime('%Y-%m-%d')
    username = request.user.username

    # Check if an assessment already exists for the user today
    existing_assessment = db.assessments.find_one({
        'username': username,
        'timestamp': {'$gte': timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)}
    })

    if existing_assessment:
        # If the assessment exists, reuse the same questions and pre-fill the selected options
        questions = existing_assessment.get('questions', [])
        selected_options = existing_assessment.get('selected_options', {})
        return render(request, 'assessment.html', {'questions': questions, 'selected_options': selected_options})

    if request.method == 'POST':
        scores = {'depression': 0, 'anxiety': 0, 'stress': 0}
        question_categories = {
            'depression': [3, 5, 10, 13, 16, 17, 21],
            'anxiety': [2, 4, 7, 9, 15, 19, 20],
            'stress': [1, 6, 8, 11, 12, 14, 18]
        }

        selected_options = {}  # Store the user's selected options in order
        questions = request.session.get('assessment_questions', [])

        for index, question in enumerate(questions):
            question_key = f'q{index + 1}'  # Use the question index as the key
            selected_option = request.POST.get(question_key, 0)
            selected_options[question_key] = selected_option  # Save the selected option

            # Calculate scores based on the question categories
            for category, q_list in question_categories.items():
                if (index + 1) in q_list:
                    scores[category] += int(selected_option)

        scores = {k: v * 2 for k, v in scores.items()}

        def get_severity(score, category):
            if category == 'depression':
                if score <= 9:
                    return 'Normal'
                elif score <= 13:
                    return 'Mild'
                elif score <= 20:
                    return 'Moderate'
                elif score <= 27:
                    return 'Severe'
                else:
                    return 'Extremely Severe'
            elif category == 'anxiety':
                if score <= 7:
                    return 'Normal'
                elif score <= 9:
                    return 'Mild'
                elif score <= 14:
                    return 'Moderate'
                elif score <= 19:
                    return 'Severe'
                else:
                    return 'Extremely Severe'
            elif category == 'stress':
                if score <= 14:
                    return 'Normal'
                elif score <= 18:
                    return 'Mild'
                elif score <= 25:
                    return 'Moderate'
                elif score <= 33:
                    return 'Severe'
                else:
                    return 'Extremely Severe'

        severity = {
            'depression': get_severity(scores['depression'], 'depression'),
            'anxiety': get_severity(scores['anxiety'], 'anxiety'),
            'stress': get_severity(scores['stress'], 'stress'),
        }

        # Store the assessment along with the questions and selected options
        db.assessments.insert_one({
            'username': username,
            'depression': scores['depression'],
            'anxiety': scores['anxiety'],
            'stress': scores['stress'],
            'severity': severity,
            'timestamp': timezone.now(),
            'questions': request.session.get('assessment_questions', []),  # Store the questions
            'selected_options': selected_options  # Store the selected options in order
        })

        return redirect('user_view')

    # Fetch questions from the database and select random questions
    questions_db = fetch_questions_from_db()
    random_questions = select_random_questions(username, questions_db, 7)
    
    questions = []
    for category, q_list in random_questions.items():
        for q in q_list:
            questions.append({"text": q})

    # Store the selected questions in the session
    request.session['assessment_questions'] = questions

    return render(request, 'assessment.html', {'questions': questions, 'selected_options': {}})

def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            auth_login(request, user)
            login_time = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            db.logins.update_one(
                {'username': username},
                {'$push': {'login_times': login_time}},
                upsert=True
            )

            if user.is_superuser:
                return JsonResponse({'status': 'success', 'redirect': 'admin_page'})
            else:
                return JsonResponse({'status': 'success', 'redirect': 'user'})
        else:
            return JsonResponse({'status': 'error', 'message': 'Invalid login credentials'}, status=400)
    else:
        return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)

def signup_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', None)
        email = request.POST.get('email', None)
        mobile = request.POST.get('mobile', None)
        age = request.POST.get('age', None)
        occupation = request.POST.get('occupation', None)
        username = request.POST.get('username', None)
        password = request.POST.get('password', None)
        gender = request.POST.get('gender', None)

        if not all([name, email, mobile, age, occupation, username, password, gender]):
            return JsonResponse({'status': 'error', 'message': 'All fields are required.'}, status=400)

        if User.objects.filter(username=username).exists():
            return JsonResponse({'status': 'error', 'message': 'Username already exists'}, status=400)

        if db.users.find_one({'email': email}):
            return JsonResponse({'status': 'error', 'message': 'Email already exists'}, status=400)

        if db.users.find_one({'mobile': mobile}):
            return JsonResponse({'status': 'error', 'message': 'Mobile number already exists'}, status=400)

        user = User.objects.create_user(username=username, email=email, password=password)
        user.first_name = name
        user.save()

        group, created = Group.objects.get_or_create(name='user')
        user.groups.add(group)

        user_data = {
            'name': name,
            'email': email,
            'mobile': mobile,
            'age': age,
            'occupation': occupation,
            'username': username,
            'gender': gender
        }
        db.users.insert_one(user_data)

        return JsonResponse({'status': 'success', 'message': 'Signup successful! Please login.'})
    else:
        return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)

@login_required
@admin_required
def admin_view(request):
    users = list(db.users.find())
    for user in users:
        user['id_str'] = str(user['_id'])

    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        if user_id:
            try:
                db.users.delete_one({'_id': ObjectId(user_id)})
                django_user = User.objects.filter(email=user.email).first()
                if django_user:
                    django_user.delete()
            except Exception as e:
                print(e)
        return redirect('admin_page')

    return render(request, 'admin.html', {'users': users})

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from pymongo import MongoClient
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from openai import OpenAI  # Import the OpenAI library
from datetime import datetime  # Import datetime for date handling

# Connect to MongoDB
client = MongoClient("mongodb://localhost:27017/")
db = client.mindmate_db

# Option mapping
option_mapping = {
    0: "Did not apply to me at all",
    1: "Applied to me to some degree, or some of the time",
    2: "Applied to me to a considerable degree, or a good part of the time",
    3: "Applied to me very much, or most of the time"
}

# Keywords for relevance check
relevant_keywords = [
    "depression", "anxiety", "stress", "mental health", "therapy", "meditation",
    "mindfulness", "counseling", "wellness", "self-care", "emotional", "psychology"
]

def is_followup_relevant(followup_text):
    """
    Check if the follow-up question is relevant to mental health.
    """
    vectorizer = TfidfVectorizer()
    keyword_matrix = vectorizer.fit_transform(relevant_keywords)
    followup_matrix = vectorizer.transform([followup_text])
    similarity = cosine_similarity(keyword_matrix, followup_matrix)
    return np.max(similarity) > 0.2  # Threshold for relevance

def generate_text_with_openrouter(prompt):
    """
    Generate text using the DeepSeek model via OpenRouter API.
    """
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key="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",  # Replace with your OpenRouter API key
    )
    try:
        completion = client.chat.completions.create(
            model="deepseek/deepseek-r1:free",  # Use the correct DeepSeek model
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000  # Adjust as needed
        )
        # Check if the completion object is valid and has the expected structure
        if completion and hasattr(completion, 'choices') and len(completion.choices) > 0:
            return completion.choices[0].message.content
        else:
            print("Error: Invalid or empty response from OpenRouter API.")
            return None
    except Exception as e:
        print(f"Error generating text with OpenRouter: {e}")
        return None

@login_required
def user_view(request):
    # Fetch user data
    user_data = db.users.find_one({'username': request.user.username})
    profile_image_url = user_data.get('profile_image_url', None) if user_data else None

    # Fetch login times
    user_logins = db.logins.find_one({'username': request.user.username})
    if user_logins:
        unique_dates = set()
        login_times = []
        for login_time in user_logins['login_times']:
            date, time = login_time.split(' ')
            if date not in unique_dates:
                unique_dates.add(date)
                login_times.append({'date': date, 'time': time})
        login_times.sort(key=lambda x: x['date'])
    else:
        login_times = []

    # Fetch assessment data
    assessments = db.assessments.find({'username': request.user.username}).sort('timestamp', 1)
    scores_by_date = {}
    all_scores = []
    for assessment in assessments:
        date = assessment['timestamp'].strftime('%Y-%m-%d')
        if date not in scores_by_date:
            scores_by_date[date] = {
                'depression': assessment['depression'],
                'anxiety': assessment['anxiety'],
                'stress': assessment['stress'],
                'severity': assessment['severity'],
            }
        all_scores.append({
            'date': date,
            'depression': assessment['depression'],
            'anxiety': assessment['anxiety'],
            'stress': assessment['stress'],
            'severity': assessment['severity'],
        })

    daily_scores = []
    for date, scores in sorted(scores_by_date.items()):
        daily_scores.append({
            'date': date,
            'depression': scores['depression'],
            'anxiety': scores['anxiety'],
            'stress': scores['stress'],
        })

    # Fetch the latest assessment
    latest_assessment = db.assessments.find_one({'username': request.user.username}, sort=[('timestamp', -1)])
    scores = latest_assessment if latest_assessment else None
    severity = latest_assessment['severity'] if latest_assessment else None
    latest_assessment_date = latest_assessment['timestamp'].strftime('%Y-%m-%d') if latest_assessment else None

    # Check if the user has taken an assessment today
    today_date = datetime.now().strftime('%Y-%m-%d')
    has_taken_assessment_today = (latest_assessment_date == today_date)

    # Fetch all recommendations from the recommendations collection
    all_recommendations = list(db.recommendations.find(
        {'username': request.user.username},
        sort=[('timestamp', -1)]  # Sort by timestamp in descending order
    ))

    # Get the latest recommendation
    latest_recommendation = all_recommendations[0]['recommendations'] if all_recommendations else None

    # Check if the user has already generated a recommendation today
    has_recommended_today = False
    if all_recommendations:
        latest_recommendation_date = all_recommendations[0]['timestamp'].strftime('%Y-%m-%d')
        has_recommended_today = (latest_recommendation_date == today_date)

    # Handle button click to generate new recommendations
    if request.method == 'POST' and 'generate_recommendations' in request.POST:
        if latest_assessment and not has_recommended_today:  # Only generate if no recommendation exists for today
            # Map selected options to text
            selected_options_text = {
                q: option_mapping.get(int(option), "Unknown") for q, option in latest_assessment['selected_options'].items()
            }

            # Create a prompt for the NLP model
            prompt = (
                f"A {user_data.get('age', 'unknown')}-year-old {user_data.get('gender', 'unknown')} "
                f"{user_data.get('occupation', 'unknown')} with the following mental health assessment:\n"
                f"Depression: {severity.get('depression', 'Not specified')}\n"
                f"Anxiety: {severity.get('anxiety', 'Not specified')}\n"
                f"Stress: {severity.get('stress', 'Not specified')}\n"
                f"Selected options:\n"
            )
            for q, option_text in selected_options_text.items():
                prompt += f"- {q}: {option_text}\n"
            prompt += (
                "Based upon the questions and the options chosen for the questions, please provide some tips on how to maintain, prevent, and cure mental illness like depression, anxiety and stress.\n"
                "Also, use the severity for depression, anxiety, and stress to provide the precautions and prevention tips.\n"
                "Use resources like age, gender, and occupation to be more specific while giving tips.\n"
                "Give the advices in points, i would like to get 5 points for depression, 5 for anxiety and 5 for stress.\n"
                "these points should cover the cure if needed, maintainance and preventive measures.\n"
            )

            # Generate recommendations using the OpenRouter API
            recommendations = generate_text_with_openrouter(prompt)

            # Store the new recommendations in the recommendations collection
            if recommendations:
                db.recommendations.insert_one({
                    'username': request.user.username,
                    'recommendations': recommendations,
                    'timestamp': datetime.now()  # Store the timestamp of the recommendation
                })
                # Update the all_recommendations list with the new recommendation
                all_recommendations.insert(0, {
                    'recommendations': recommendations,
                    'timestamp': datetime.now()
                })
                latest_recommendation = recommendations
                has_recommended_today = True  # Update the flag since a new recommendation was generated
            else:
                print("Failed to generate recommendations. Keeping the existing ones.")

    # Render the user dashboard with recommendations
    return render(request, 'users.html', {
        'profile_image_url': profile_image_url,
        'login_times': login_times,
        'scores': scores,
        'severity': severity,
        'daily_scores': daily_scores,
        'all_scores': all_scores,
        'latest_assessment_date': latest_assessment_date,
        'has_taken_assessment_today': has_taken_assessment_today,
        'user_data': user_data,
        'recommendations': latest_recommendation,  # Pass the latest recommendation to the template
        'all_recommendations': all_recommendations,  # Pass all recommendations to the template
        'has_recommended_today': has_recommended_today  # Pass the flag to the template
    })

def logout_view(request):
    @login_required
    def get_user_info(request):
        user_data = db.users.find_one({'username': request.user.username}, {'_id': 0, 'name': 1, 'username': 1, 'email': 1, 'mobile': 1, 'age': 1, 'occupation': 1, 'gender': 1})
        if user_data:
            return JsonResponse({'status': 'success', 'data': user_data})
        else:
            return JsonResponse({'status': 'error', 'message': 'User not found'}, status=404)
    logout(request)
    return redirect('index')

@login_required
def upload_profile_image(request):
    if request.method == 'POST':
        profile_image = request.FILES.get('profile_image')
        if profile_image:
            profile_images_dir = os.path.join(settings.MEDIA_ROOT, 'profile_images')
            os.makedirs(profile_images_dir, exist_ok=True)

            path = os.path.join(profile_images_dir, profile_image.name)
            with open(path, 'wb+') as destination:
                for chunk in profile_image.chunks():
                    destination.write(chunk)

            profile_image_url = f'/media/profile_images/{profile_image.name}'
            db.users.update_one(
                {'username': request.user.username},
                {'$set': {'profile_image_url': profile_image_url}}
            )
            
            print(f"Profile image saved to: {path}")
            print(f"Profile image URL: {profile_image_url}")
            
            return JsonResponse({'success': True})
    return JsonResponse({'success': False})
