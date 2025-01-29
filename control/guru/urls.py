from django.urls import path
from . import views


urlpatterns = [
    path('', views.index, name='index'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('admin_page/', views.admin_view, name='admin_page'),  # Placeholder for admin view
    path('user/', views.user_view, name='user_view'),
    path('index.html', views.index, name='index_html'),  # Add this line
    path('logout/', views.logout_view, name='logout'),  # Add this line
]
