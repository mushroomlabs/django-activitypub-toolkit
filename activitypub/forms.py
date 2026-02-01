import re
import unicodedata

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.http import Http404
from django.urls import resolve
from oauth2_provider.forms import AllowForm

from .models import ActorContext, Domain, Identity, Reference


class IdentityAuthorizationForm(AllowForm):
    identity = forms.ModelChoiceField(queryset=Identity.objects.none())

    def __init__(self, user, *args, **kw):
        super().__init__(*args, **kw)
        self.fields["identity"].queryset = Identity.objects.filter(user=user)


class CreateIdentityForm(forms.Form):
    domain = forms.ModelChoiceField(
        queryset=Domain.objects.filter(instance__open_registrations=True, local=True),
        required=True,
        label="Domain",
        help_text="Select the domain for your new identity",
    )

    preferred_username = forms.CharField(
        max_length=100,
        required=True,
        label="Username",
        help_text="Only letters, numbers, and underscores allowed",
        validators=[
            RegexValidator(
                regex=r"^[a-zA-Z0-9_]+$",
                message="Username can only contain letters, numbers, and underscores",
            )
        ],
    )

    actor_path = forms.CharField(
        max_length=200,
        required=True,
        label="Actor Path",
        help_text="URL path for your actor (e.g., actors/username)",
        initial="actors/",
    )

    display_name = forms.CharField(
        max_length=255,
        required=False,
        label="Display Name",
        help_text="Your public display name (optional)",
    )

    actor_type = forms.ChoiceField(
        choices=[
            (ActorContext.Types.PERSON, "Person (regular account)"),
            (ActorContext.Types.SERVICE, "Service (bot account)"),
        ],
        initial=ActorContext.Types.PERSON,
        required=True,
        label="Account Type",
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        # Set initial actor_path based on username if provided
        if self.data.get("preferred_username"):
            username = self.data.get("preferred_username")
            self.fields["actor_path"].initial = f"actors/{username}"

    def clean_preferred_username(self):
        username = self.cleaned_data["preferred_username"]

        # Apply unicode normalization (NFC)
        username = unicodedata.normalize("NFC", username)

        # Convert to lowercase
        username = username.lower()

        # Trim whitespace
        username = username.strip()

        # Validate again after normalization
        if not username:
            raise ValidationError("Username cannot be empty after normalization")

        if not username.replace("_", "").isalnum():
            raise ValidationError("Username can only contain letters, numbers, and underscores")

        return username

    def clean_actor_path(self):
        actor_path = self.cleaned_data["actor_path"]

        # Trim whitespace
        actor_path = actor_path.strip()

        # Remove leading/trailing slashes
        actor_path = actor_path.strip("/")

        # Validate path format (no spaces, basic URL path characters)
        if not actor_path:
            raise ValidationError("Actor path cannot be empty")

        if not re.match(r"^[a-zA-Z0-9_\-/]+$", actor_path):
            raise ValidationError(
                "Actor path can only contain letters, numbers, underscores, hyphens, and slashes"
            )

        return actor_path

    def clean(self):
        cleaned_data = super().clean()
        domain = cleaned_data.get("domain")
        username = cleaned_data.get("preferred_username")
        actor_path = cleaned_data.get("actor_path")

        if not domain or not username or not actor_path:
            return cleaned_data

        # Build the full actor URI
        actor_uri = f"{domain.url}/{actor_path}"

        # Check 1: Username must be unique on this domain
        username_taken = ActorContext.objects.filter(
            preferred_username=username, reference__domain=domain
        ).exists()

        if username_taken:
            msg = f"Username '{username}' is already taken on {domain.netloc}"
            raise ValidationError({"preferred_username": msg})

        # Check 2: The URI must not already exist as a Reference
        if Reference.objects.filter(uri=actor_uri).exists():
            msg = f"The URL {actor_uri} already exists. Please choose a different path."
            raise ValidationError({"actor_path": msg})

        # Check 3: The path should not resolve to an existing route
        # This is a bit tricky - the catch-all route will probably match anything,
        # so we need to exclude it from the functions that

        protected_paths = [
            "api",
            "admin",
            "media",
            "static",
            ".well-known",
            "nodeinfo",
            "inbox",
            "outbox",
        ]

        if any([actor_path.startswith(path) for path in protected_paths]):
            raise ValidationError(
                {"actor_path": f"The path '{actor_path}' is reserved. Please choose another."}
            )

        # Final check
        try:
            resolve(actor_path)
        except Http404:
            pass
        else:
            msg = f"The path '{actor_path}' is already in use. Please choose another."
            raise ValidationError({"actor_path": msg})

        return cleaned_data
