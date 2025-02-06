import os
import random
from datetime import datetime
import json
from bson import ObjectId
from django.conf import settings
from django.contrib.auth import authenticate, login as auth_login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from pymongo import MongoClient
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .decorators import admin_required
import openai
from openai import OpenAI

# MongoDB setup
client = MongoClient("mongodb://localhost:27017/")
db = client.mindmate_db
questions_collection = db.questions  # Assuming your collection is named 'questions'
key="xxxx" # Replace with your OpenAI API key
archive_collection = db.archive_conversations
journals = db['journals']

# Option mapping
option_mapping = {
    0: "Did not apply to me at all",
    1: "Applied to me to some degree, or some of the time",
    2: "Applied to me to a considerable degree, or a good part of the time",
    3: "Applied to me very much, or most of the time"
}
collection = db.conversations


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

def select_random_questions(username, questions_db, num_questions_per_category=7):
    # Access the user_questions collection
    user_record = db.user_questions.find_one({"username": username})
    
    if user_record:
        previously_asked_questions = user_record.get("questions", {})
    else:
        previously_asked_questions = {}

    selected_questions = {}
    for category, questions in questions_db.items():
        # Select random questions from the full list (allow reuse)
        if len(questions) >= num_questions_per_category:
            selected_questions[category] = random.sample(questions, num_questions_per_category)
        else:
            # If there are fewer questions than requested, select all available questions
            print(f"Not enough questions in category '{category}' to select {num_questions_per_category} questions.")
            selected_questions[category] = questions

        # Update the previously asked questions for this user
        previously_asked_questions[category] = previously_asked_questions.get(category, []) + selected_questions[category]
    
    # Update the user_questions collection
    db.user_questions.update_one(
        {"username": username},
        {"$set": {"questions": previously_asked_questions}},
        upsert=True
    )

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

def generate_text_with_openrouter(prompt):
    """
    Generate text using the DeepSeek model via OpenRouter API.
    """
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key= key,  # Replace with your OpenRouter API key
    )
    try:
        completion = client.chat.completions.create(
            model="meta-llama/llama-3.2-90b-vision-instruct:free",  # Use the correct DeepSeek model
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

    # Fetch journal entries and calculate average scores
    journal_doc = db.journals.find_one({'user': request.user.username})
    journal_entries = journal_doc.get('journals', []) if journal_doc else []
    db_average_scores = journal_doc.get('average_scores', {}) if journal_doc else {}

    average_scores = {
        'mood': db_average_scores.get('mood', 0),
        'diet': db_average_scores.get('diet', 0),
        'sleep': db_average_scores.get('sleep', 0),
        'physical_activity': db_average_scores.get('physical_activity', 0)
    }

    # Create a prompt for journal analysis
    journal_prompt = (
        f"Analyze the following journal entries for the user {request.user.username}:\n"
        f"Journal Entries: {journal_entries}\n"
        f"Average Scores: {average_scores}\n"
        f"Based on the entries, provide insights on mood, diet, sleep, and physical activity."
    )
    print(journal_prompt)

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
                f"{user_data.get('occupation', 'unknown')} with:\n"
                f"Mental Health Assessment:\n"
                f"- Depression: {severity.get('depression', 'Not specified')}\n"
                f"- Anxiety: {severity.get('anxiety', 'Not specified')}\n"
                f"- Stress: {severity.get('stress', 'Not specified')}\n"
                f"\nLifestyle Insights from Journal Entries:\n"
                f"- Mood: {average_scores['mood']:.1f}% (Average Score)\n"
                f"- Diet: {average_scores['diet']:.1f}% (Average Score)\n"
                f"- Sleep: {average_scores['sleep']:.1f}% (Average Score)\n"
                f"- Physical Activity: {average_scores['physical_activity']:.1f}% (Average Score)\n"
                f"\nRecent Journal Entries Summary:\n"
            )

            # Add the last 3 journal entry excerpts
            for entry in journal_entries[-3:]:
                prompt += f"- {entry['content'][:100]}...\n"

            prompt += (
                f"\nSelected Assessment Options:\n"
            )
            for q, option_text in selected_options_text.items():
                prompt += f"- {q}: {option_text}\n"

            prompt += (
                """\nYou are a compassionate mental health assistant. Please:\n"""
                """1. Start by acknowledging the user's mental health status and lifestyle insights\n"""
                """2. Provide specific recommendations that connect both assessment results and journal patterns\n"""
                """3. For each category (depression, anxiety, stress), give 5 actionable tips considering:\n"""
                """   - Their occupation and demographic\n"""
                """   - Their daily habits revealed by journal entries\n"""
                """   - Practical implementation strategies\n"""
                """4. Include reality checks and maintenance strategies\n"""
                """5. Structure response with clear headings and bullet points\n"""
                """6. Use formal but compassionate tone with emojis for emphasis"""
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
        'has_recommended_today': has_recommended_today,  # Pass the flag to the template
        'average_scores': average_scores,  # Pass average scores to the template
        'journal_entries': journal_entries,  # Pass journal entries to the template
        'journal_prompt': journal_prompt  # Pass the journal prompt to the template
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

def save_conversation(user_id, role, message, timestamp):
    """
    Save a conversation message to MongoDB.
    """
    date_str = timestamp.date().isoformat()  # Convert date to string
    conversation_data = {
        "role": role,
        "message": message,
        "timestamp": timestamp
    }
    # Find the document for the specific user and date, and update it
    collection.update_one(
        {"user_id": user_id, "date": date_str},
        {"$push": {"messages": conversation_data}},
        upsert=True
    )

def get_conversation(user_id):
    """
    Retrieve entire conversation history for a specific user.
    """
    conversations = collection.find({"user_id": user_id})
    messages = []
    for conv in conversations:
        messages.extend(conv.get("messages", []))
    return messages

def build_prompt(user_message, user_conversation, user_data=None, severity=None, include_helplines=False, average_scores=None):
    """
    Build the prompt for the OpenRouter API call based on the conditions.
    """
    base_prompt = f"""
    You are an AI assistant named MindMate AI designed to provide support for mental health, depression, anxiety, and stress. Respond to the following user message only if it is relevant to these topics. Allow the words like "latest report information" and "helpline". If the message is not relevant, respond with "Sorry, I can only assist with mental health-related topics."
    Allow general greetings and small talk to maintain a conversational tone.
    Also, ask users about their health and mood.
    When asked about latest report information, provide the user with the latest mental health assessment report showing the gender, age, occupation, and the severity of depression, anxiety, and stress.
    Keep it in a conversational tone. Don't say too much information if not required or asked, and keep the responses short and simple.
    """
    
    # Add user data and severity information if available
    if user_data and severity:
        user_info = f"""
        User Information:
        Age: {user_data.get('age', 'unknown')}
        Gender: {user_data.get('gender', 'unknown')}
        Occupation: {user_data.get('occupation', 'unknown')}
        Latest Mental Health Assessment:
        Depression: {severity.get('depression', 'Not specified')}
        Anxiety: {severity.get('anxiety', 'Not specified')}
        Stress: {severity.get('stress', 'Not specified')}
        """
        base_prompt += user_info
    
    # Add journal insights if average_scores are provided
    if average_scores:
        journal_prompt = f"""
        Lifestyle Insights from Journal Entries:
        - Mood: {average_scores.get('mood', 0):.1f}% (Average Score)
        - Diet: {average_scores.get('diet', 0):.1f}% (Average Score)
        - Sleep: {average_scores.get('sleep', 0):.1f}% (Average Score)
        - Physical Activity: {average_scores.get('physical_activity', 0):.1f}% (Average Score)
        """
        base_prompt += journal_prompt
    
    # Add helpline numbers if requested
    if include_helplines:
        helplines = """
        Additionally, provide the user with Indian helpline numbers for mental health support when appropriate. The helplines are:
        - Kiran Mental Health Rehabilitation Helpline: 1800-599-0019
        - Snehi Helpline for Emotional Support: 91-22-2772 6771
        - Fortis Mental Health Helpline: 91-8376804102
        """
        base_prompt += helplines
    
    # Format the conversation history
    conversation_history = "\n".join([f"{msg['role']}: {msg['message']}" for msg in user_conversation])
    base_prompt += f"\nConversation history:\n{conversation_history}\nUser message: {user_message}"
    
    return base_prompt

def generate_chat_with_openrouter(user_id, user_message, user_conversation, user_data=None, severity=None, include_helplines=False, include_journal_info=False):
    """
    Generate text using the DeepSeek model via OpenRouter API.
    """
    client = openai.OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=key,  # Replace with your OpenRouter API key
    )
    try:
        # Build the prompt dynamically
        full_prompt = build_prompt(user_message, user_conversation, user_data, severity, include_helplines, include_journal_info)
        completion = client.chat.completions.create(
            model="meta-llama/llama-3.2-90b-vision-instruct:free",  # Use the correct DeepSeek model
            messages=[
                {"role": "system", "content": full_prompt}
            ],
            max_tokens=2000  # Adjust as needed
        )
        # Check if the completion object is valid and has the expected structure
        if completion and hasattr(completion, 'choices') and len(completion.choices) > 0:
            response_content = completion.choices[0].message.content
            # Save the response to the conversation history
            save_conversation(user_id, "assistant", response_content, datetime.now())
            return response_content
        else:
            print("Error: Invalid or empty response from OpenRouter API.")
            return None
    except Exception as e:
        print(f"Error generating text with OpenRouter: {e}")
        return None

@csrf_exempt
def chatbot(request):
    if request.method == "POST":
        user_id = request.user.username  # Use the logged-in user's username
        user_message = request.POST.get("message")
        
        # Save the user message to the conversation history
        save_conversation(user_id, "user", user_message, datetime.now())
        
        # Retrieve entire conversation history for the user
        user_conversation = get_conversation(user_id)
        
        # Fetch user data and assessment information for personalized responses
        user_data = db.users.find_one({'username': user_id})
        latest_assessment = db.assessments.find_one({'username': user_id}, sort=[('timestamp', -1)])
        severity = latest_assessment['severity'] if latest_assessment else None
        
        # Fetch journal entries and calculate average scores
        journal_doc = db.journals.find_one({'user': user_id})
        journal_entries = journal_doc.get('journals', []) if journal_doc else []
        db_average_scores = journal_doc.get('average_scores', {}) if journal_doc else {}
        
        average_scores = {
            'mood': db_average_scores.get('mood', 0),
            'diet': db_average_scores.get('diet', 0),
            'sleep': db_average_scores.get('sleep', 0),
            'physical_activity': db_average_scores.get('physical_activity', 0)
        }
        
        # Determine if helplines or user information should be included in the prompt
        include_helplines = False
        include_user_info = False
        include_journal_info = False
        if "latest report" in user_message.lower() or "reports information" in user_message.lower():
            include_user_info = True
        if "helpline" in user_message.lower() or "help based on my reports" in user_message.lower():
            include_helplines = True
            if "help based on my reports" in user_message.lower():
                include_user_info = True
        if "journal information" in user_message.lower() or "journal" in user_message.lower():
            include_journal_info = True
        
        # Generate response with journal information included
        response_text = generate_chat_with_openrouter(
            user_id,
            user_message,
            user_conversation,
            user_data if include_user_info else None,
            severity if include_user_info else None,
            include_helplines,
            average_scores if include_journal_info else None  # Pass the average scores to the response generation
        )
        
        if response_text:
            return JsonResponse({"response": response_text})
        else:
            return JsonResponse({"error": "Failed to generate a response from the model."})
    
    elif request.method == "GET":
        user_id = request.user.username  # Use the logged-in user's username
        # Retrieve entire conversation history for the user
        user_conversation = get_conversation(user_id)
        # Prepare the conversation history for display
        conversation_history = [{"role": msg["role"], "message": msg["message"]} for msg in user_conversation]
        return JsonResponse({"conversation_history": conversation_history})
    
    return JsonResponse({"error": "Invalid request method."})

@csrf_exempt
def archive_chat(request):
    if request.method == "POST":
        try:
            # Get the current user's identifier
            user_id = request.user.username  # Changed to match conversation storage format
            
            # 1. Retrieve current conversations
            current_conversations = list(collection.find({"user_id": user_id}))
            
            if not current_conversations:
                return JsonResponse({"status": "success", "message": "No chats to archive"})
            
            # 2. Archive the conversations
            archive_result = archive_collection.insert_one({
                "user_id": user_id,
                "archived_at": datetime.now(),
                "conversations": current_conversations
            })
            
            # 3. Delete from original collection with verification
            delete_result = collection.delete_many({"user_id": user_id})
            
            # Verify deletion
            if delete_result.deleted_count == len(current_conversations):
                return JsonResponse({
                    "status": "success",
                    "archived_count": len(current_conversations),
                    "deleted_count": delete_result.deleted_count
                })
            else:
                # Handle partial deletion
                archive_collection.delete_one({"_id": archive_result.inserted_id})
                return JsonResponse({
                    "status": "error",
                    "message": "Partial deletion occurred, archive rolled back"
                })
                
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})
    
    return JsonResponse({"status": "error", "message": "Invalid request method"})

import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId
import openai
import json
import time

def analyze_journal_content(content):
    client = openai.OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=key,
    )

    prompt = f"""Please analyze the following journal entry and evaluate the user's mood, diet, sleep, and physical activity. 
For each aspect, provide a score of 1 for positive mentions and 0 for negative mentions. 
If an aspect is not mentioned, indicate that it was not mentioned.

Output the results in a structured format:
- mood: {{ "score": 0, "mentioned": true }}
- diet: {{ "score": 0, "mentioned": true }}
- sleep: {{ "score":0, "mentioned": false }}
- physical_activity: {{ "score": 0, "mentioned": true }}

Journal Entry: {content}
Response:"""

    retries = 3
    for attempt in range(retries):
        try:
            completion = client.chat.completions.create(
                model="meta-llama/llama-3.2-90b-vision-instruct:free",
                messages=[{"role": "system", "content": prompt}],
                max_tokens=6000
            )

            print(f"Raw API response: {completion}")  # Debug line

            if completion and completion.choices:
                response = completion.choices[0].message.content
                print(f"Response content: {response}")  # Debug line

                if not response:
                    print("Received an empty response from the API.")  # Debug line
                    return None

                analysis = {
                    "mood": {"score": 0, "mentioned": False},
                    "diet": {"score": 0, "mentioned": False},
                    "sleep": {"score":0, "mentioned": False},
                    "physical_activity": {"score": 0, "mentioned": False}
                }

                if 'mood: { "score": 1, "mentioned": true }' in response:
                    analysis["mood"]["score"] = 1
                    analysis["mood"]["mentioned"] = True
                if 'diet: { "score": 1, "mentioned": true }' in response:
                    analysis["diet"]["score"] = 1
                    analysis["diet"]["mentioned"] = True
                if 'sleep: { "score": 1, "mentioned": true }' in response:
                    analysis["sleep"]["score"] = 1
                    analysis["sleep"]["mentioned"] = True
                if 'physical_activity: { "score": 1, "mentioned": true }' in response:
                    analysis["physical_activity"]["score"] = 1
                    analysis["physical_activity"]["mentioned"] = True

                return analysis
            else:
                print("No choices returned from the API response.")  # Debug line
                return None
        except openai.error.RateLimitError:
            print(f"Rate limit exceeded. Retrying in {2 ** attempt} seconds...")
            time.sleep(2 ** attempt)
        except Exception as e:
            print(f"Error analyzing journal: {e}")  # Debug line
            return None


@csrf_exempt
def save_journal(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            content = data.get('content')

            if not request.user.is_authenticated:
                return JsonResponse({'success': False, 'error': 'User not authenticated'}, status=401)

            # Analyze the journal entry content
            analysis = analyze_journal_content(content)
            
            # Save the new journal entry with analysis
            journal_entry = {
                'content': content,
                'timestamp': datetime.now(),
                'analysis': analysis  # Store the analysis with the entry
            }
            
            # Insert the new journal entry into the user's document
            result = db.journals.update_one(
                {'user': request.user.username},
                {'$push': {'journals': journal_entry}},
                upsert=True
            )
            # Analyze ONLY the new journal entry
            analysis = analyze_journal_content(content)
            
            if analysis:
                # Get existing cumulative scores from database
                user_data = journals.find_one({'user': request.user.username})
                cumulative_scores = user_data.get('cumulative_scores', {
                    'mood': {'score': 0, 'count': 0},
                    'diet': {'score': 0, 'count': 0},
                    'sleep': {'score': 0, 'count': 0},
                    'physical_activity': {'score': 0, 'count': 0}
                })

                # Update cumulative scores with new analysis
                for entity in ['mood', 'diet', 'sleep', 'physical_activity']:
                    entity_data = analysis.get(entity, {'score': 0, 'mentioned': False})
                    if entity_data['mentioned']:
                        cumulative_scores[entity]['score'] += entity_data['score']
                        cumulative_scores[entity]['count'] += 1  # Increment count for mentioned
                    else:
                        # If mentioned is true and score is 0, still increment count
                        if entity_data['score'] == 0:
                            cumulative_scores[entity]['count'] += 1

                # Calculate new average scores
                average_scores = {}
                for entity in cumulative_scores:
                    total = cumulative_scores[entity]['score']
                    count = cumulative_scores[entity]['count']
                    average_scores[entity] = (total / count * 10) if count > 0 else 0

                # Update database with new scores
                journals.update_one(
                    {'user': request.user.username},
                    {'$set': {
                        'cumulative_scores': cumulative_scores,
                        'average_scores': average_scores
                    }}
                )

            return JsonResponse({'success': True})
        except Exception as e:
            print(f"Error: {e}")
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

def convert_objectid_to_str(data):
    """Recursively convert ObjectId instances to strings in a data structure."""
    if isinstance(data, list):
        return [convert_objectid_to_str(item) for item in data]
    elif isinstance(data, dict):
        return {key: convert_objectid_to_str(value) for key, value in data.items()}
    elif isinstance(data, ObjectId):
        return str(data)
    return data

@login_required
@csrf_exempt
def get_journals(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    all_journals = list(journals.find({'user': request.user.username}).sort('journals.timestamp', -1))
    
    for user_journal in all_journals:
        for journal in user_journal['journals']:
            if '_id' not in journal:
                journal['_id'] = ObjectId()  # Ensure each journal entry has an _id
                journals.update_one(
                    {'user': request.user.username, 'journals.timestamp': journal['timestamp']},
                    {'$set': {'journals.$._id': journal['_id']}}
                )
            journal['_id'] = str(journal['_id'])  # Convert ObjectId to string
            journal['timestamp'] = journal['timestamp'].isoformat()
            journal['scores'] = journal.get('scores', {})
            journal['average_score'] = journal.get('average_scores', {})
    
    # Convert all ObjectId instances to strings before returning
    all_journals = convert_objectid_to_str(all_journals)
    
    return JsonResponse(all_journals, safe=False)

@login_required
@csrf_exempt
def get_journal(request, journal_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    try:
        journal_entry = journals.find_one({
            'journals._id': ObjectId(journal_id),
            'user': request.user.username
        }, {'journals.$': 1})
        
        if journal_entry and 'journals' in journal_entry:
            journal = journal_entry['journals'][0]
            journal['_id'] = str(journal['_id'])  # Convert ObjectId to string
            journal['timestamp'] = journal['timestamp'].isoformat()
            journal['scores'] = journal.get('scores', {})
            journal['average_score'] = journal.get('average_scores', {})
            return JsonResponse(journal)
        
        return JsonResponse({'error': 'Journal not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': f'Invalid journal ID: {e}'}, status=400)
    
def journal_view(request):
    return render(request, 'journal.html')

@csrf_exempt
def delete_journal(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            entry_id = data.get('entry_id')

            if not request.user.is_authenticated:
                return JsonResponse({'success': False, 'error': 'User not authenticated'}, status=401)

            # Find and delete the journal entry
            result = journals.update_one(
                {'user': request.user.username},
                {'$pull': {'journals': {'_id': ObjectId(entry_id)}}}
            )

            if result.modified_count > 0:
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False, 'error': 'Entry not found'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    return JsonResponse({'success': False, 'error': 'Invalid request method'})
