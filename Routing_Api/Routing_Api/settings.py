import os
import posixpath
import raven
from celery.schedules import crontab

BUSNOW_ENVIRONMENT = os.environ.get('BUSNOW_ENVIRONMENT', None)

RAVEN_CONFIG = {
    # 'dsn': os.environ.get('SENTRY_DSN'),
    'environment': BUSNOW_ENVIRONMENT,
    'auto_log_stacks': True
}
# SENTRY_CLIENT = 'raven.contrib.django.raven_compat.DjangoClient'

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.9/howto/deployment/checklist/

SECRET_KEY = os.environ.get('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = BUSNOW_ENVIRONMENT == 'DEBUGGING'

# Who can access the server? ['localhost', '127.0.0.1'] for local debugging
ALLOWED_HOSTS = list(os.environ.get('ALLOWED_HOSTS', '*'))
#ALLOWED_HOSTS = list('*')

# Application definition

INSTALLED_APPS = [
    # Add your apps here to enable them
    #   'django_dbconn_retry',
    'raven.contrib.django.raven_compat',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    #'django.contrib.gis',
    'rest_framework',
    'health_check',                             # required
    'health_check.db',                          # stock Django health checkers
    'health_check.cache',
    'health_check.storage',
    'Routing_Api.Mobis',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # 'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'Routing_Api.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'Routing_Api.wsgi.application'


# Database
# https://docs.djangoproject.com/en/1.9/ref/settings/#databases
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'CONN_MAX_AGE': 0,
        'NAME': os.environ.get('POSTGRES_DB'),
        'USER': os.environ.get('POSTGRES_USER'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD'),
        'HOST': os.environ.get('POSTGRES_HOST'),
        'PORT': os.environ.get('POSTGRES_PORT')
    }
}

# https://dev.to/weplayinternet/upgrading-to-django-3-2-and-fixing-defaultautofield-warnings-518n
# https://docs.djangoproject.com/en/3.2/ref/models/fields/#autofield
# Specifies the type of automatically created primary keys
DEFAULT_AUTO_FIELD='django.db.models.AutoField'

# Password validation
# https://docs.djangoproject.com/en/1.9/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/1.9/topics/i18n/

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.9/howto/static-files/

STATIC_URL = '/static/'

STATIC_ROOT = posixpath.join(*(BASE_DIR.split(os.path.sep) + ['static']))

# rest framework settings:
if DEBUG:
    REST_FRAMEWORK = {
        'DEFAULT_VERSIONING_CLASS': 'rest_framework.versioning.AcceptHeaderVersioning',
        'DEFAULT_THROTTLE_CLASSES': [
            'rest_framework.throttling.AnonRateThrottle',
            'rest_framework.throttling.UserRateThrottle',
        ],
        'DEFAULT_THROTTLE_RATES': {
            'anon': os.environ.get('REST_THROTTLINGRATE_ANON', '300') + '/minute',
            'user': os.environ.get('REST_THROTTLINGRATE_USER', '100') + '/second',
        }
    }
    INTERNAL_IPS = ['127.0.0.1']
    MIDDLEWARE = ['debug_toolbar.middleware.DebugToolbarMiddleware'] + MIDDLEWARE
    INSTALLED_APPS = ['debug_toolbar'] + INSTALLED_APPS
else:
    REST_FRAMEWORK = {
        'DEFAULT_VERSIONING_CLASS': 'rest_framework.versioning.AcceptHeaderVersioning',
        'DEFAULT_RENDERER_CLASSES': (
            'rest_framework.renderers.JSONRenderer',
        ),
        'DEFAULT_THROTTLE_CLASSES': [
            'rest_framework.throttling.AnonRateThrottle',
            'rest_framework.throttling.UserRateThrottle',
        ],
        'DEFAULT_THROTTLE_RATES': {
            'anon': os.environ.get('REST_THROTTLINGRATE_ANON', '3') + '/minute',
            'user': os.environ.get('REST_THROTTLINGRATE_USER', '1') + '/second',
        }
    }

ROUTING_TIMEOFFSET_MINMINUTESTOORDERFROMNOW = (int)(os.environ.get('ROUTING_FREEZE_TIME_DELTA', '15')) 

# Other Celery settings
CELERY_BEAT_SCHEDULE = {
    'freeze-routes': {
        'task': 'Routing_Api.Mobis.tasks.freeze_routes',
        'schedule': crontab(minute='*/1'),
        'args': (ROUTING_TIMEOFFSET_MINMINUTESTOORDERFROMNOW,)
    },
    'delete-routes': {
        'task': 'Routing_Api.Mobis.tasks.delete_routes',
        'schedule': crontab(minute='*/10'),
        'args': ()
    },
    'delete-empty-routes': {
        'task': 'Routing_Api.Mobis.tasks.delete_empty_routes',
        'schedule': crontab(minute='*/10'),
        'args': ()
    },
    'delete-unused-nodes': {
        'task': 'Routing_Api.Mobis.tasks.delete_unused_nodes',
        'schedule': crontab(minute='*/10'),
        'args': ()
    },
    'split-routes': {
        'task': 'Routing_Api.Mobis.tasks.split_routes',
        'schedule': crontab(minute='*/5'),
        'args': ()
    },
    'check-routing-data': {
        'task': 'Routing_Api.Mobis.tasks.check_routing_data',
        'schedule': crontab(minute='*/1'),
        'args': ()
    }
}

RABBITMQ_HOST = os.environ.get('RABBITMQ_HOST')
RABBITMQ_USER = os.environ.get('RABBITMQ_USERNAME')
RABBITMQ_PASS = os.environ.get('RABBITMQ_PASSWORD')
RABBITMQ_VHOST = os.environ.get(
    'RABBITMQ_VHOST', '/').replace("'", "").replace('"', '')

CELERY_TIMEZONE = 'UTC'
CELERY_BROKER_URL = f'amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}/{RABBITMQ_VHOST}'

timestamp = datetime.datetime.now().strftime("%Y%m%d_%H-%M-%S")
log_filename_routing = f"../log-storage-routing/routing_{timestamp}.log"
log_file_django = f"../log-storage-routing/django_{timestamp}.log"

directory_path = os.path.dirname(log_filename_routing)
if not os.path.exists(directory_path):
    os.makedirs(directory_path)
    print(f"The directory '{directory_path}' was created.")

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'root': {
        'level': 'WARNING',
        # 'handlers': ['sentry'],
    },
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
        'require_debug_true': {
            '()': 'django.utils.log.RequireDebugTrue',
        },
    },
    'formatters': {
        'django.server': {
            '()': 'django.utils.log.ServerFormatter',
            'format': '[%(server_time)s] %(message)s',
        },
        'verbose': {
            'format': '{levelname} | {asctime} | {module}.py | {message}', # {process:d} {thread:d}
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        # 'sentry': {
        #     # To capture more than ERROR, change to WARNING, INFO, etc., maximum logging is DEBUG
        #     'level': 'WARNING',
        #     'class': 'raven.contrib.django.raven_compat.handlers.SentryHandler',
        # },
        'console': {
            'level': 'DEBUG',
            'filters': ['require_debug_true'],
            'class': 'logging.StreamHandler',
        },
        'console_debug_false': {
            'level': 'DEBUG',
            'filters': ['require_debug_false'],
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'django.server': {
            'level': 'WARNING',
            'class': 'logging.StreamHandler',
            'formatter': 'django.server',
        },
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler'
        },
        "log_file_django": {
            "level": "WARNING",
            "class": "logging.FileHandler",
            "filename": log_file_django
        },
        "log_file_routing": {
            "level": "DEBUG",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": log_filename_routing,
            'maxBytes': 10 * 1024 * 1024,  # 10 MB per logfile
            'backupCount': 20,  # 20 Backup-files
            'formatter': 'verbose',
        }
    },
    'loggers': {
        'routing.Maps': {
            'handlers': ['console', 'console_debug_false', 'log_file_routing'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'routing.routing': {
            'handlers': ['console', 'console_debug_false', 'log_file_routing'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'routing.rutils': {
            'handlers': ['console', 'console_debug_false', 'log_file_routing'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'Mobis.tasks': {
            'handlers': ['console', 'console_debug_false', 'log_file_routing'],
            'level': 'INFO',
            'propagate': True,
        },
        'Mobis.apifunctions': {
            'handlers': ['console', 'console_debug_false', 'log_file_routing'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'Mobis.services': {
            'handlers': ['console', 'console_debug_false', 'log_file_routing'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'Mobis.EventBus': {
            'handlers': ['console', 'console_debug_false', 'log_file_routing'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'mockups.db_busses': {
            'handlers': ['console', 'console_debug_false', 'log_file_routing'],
            'level': 'INFO',
            'propagate': True,
        },
        'django': {
            'handlers': ['console', 'console_debug_false', 'log_file_django'],
            'level': 'WARNING',
            'propagate': True,
        },
        'django.server': {
            'handlers': ['django.server', 'log_file_django'],
            'level': 'WARNING',
            'propagate': True,
        },
        'pika.adapters.blocking_connection': {
            'level': 'WARNING',
            'propagate': True,
        },
        'pika.adapters.base_connection': {
            'level': 'WARNING',
            'propagate': True,
        },
        'shapely.geos': {
            'level': 'WARNING',
            'propagate': True,
        }
    }
}