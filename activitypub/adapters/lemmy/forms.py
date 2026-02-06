from django import forms

from .models import LocalSite


class LocalSiteForm(forms.ModelForm):
    name = forms.CharField(max_length=50, required=True)
    sidebar = forms.CharField(widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].initial = self.instance.site.as2.name
        self.fields["sidebar"].initial = self.instance.site.as2.summary

    def save(self, commit=True):
        instance = super().save(commit=commit)

        # Save name to context
        if "name" in self.cleaned_data:
            instance.site.as2.name = self.cleaned_data["name"]
        if "sidebar" in self.cleaned_data:
            instance.site.as2.summary = self.cleaned_data["sidebar"]
        if commit:
            instance.site.as2.save()

        return instance

    class Meta:
        model = LocalSite
        fields = "__all__"
