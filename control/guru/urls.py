from django.urls import path
from . import views
from django.conf.urls.static import static
from django.conf import settings


urlpatterns = [
    path('', views.index, name='index'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('admin_page/', views.admin_view, name='admin_page'),  # Placeholder for admin view
    path('user/', views.user_view, name='user_view'),
    path('index.html', views.index, name='index_html'),  # Add this line
    path('logout/', views.logout_view, name='logout'),  # Add this line
    path('upload_profile_image/', views.upload_profile_image, name='upload_profile_image'),
    path('assessment/', views.assessment, name='assessment'),
    path('chatbot/', views.chatbot, name='chatbot'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)