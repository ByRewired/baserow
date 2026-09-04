from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("database", "0219_button_field_smtp_email_action"),
    ]

    operations = [
        migrations.AlterField(
            model_name="formview",
            name="mode",
            field=models.TextField(
                choices=[("form", "form")],
                default="form",
                help_text="Configurable mode of the form.",
                max_length=64,
            ),
        ),
    ]
