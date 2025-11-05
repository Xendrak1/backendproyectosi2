from ...usuario.models import User, Persona

def run():
    usuarios_data = [
        {
            "username": "user1",
            "email": "user1@gmail.com",
            "password": "123456",
            "is_staff": False,
            
            "nombre": "Christian",
            "apellido": "Torrez",
            "ci": "123456",
            "telefono": "77777777"
        },
        {
            "username": "user2",
            "email": "user2@gmail.com",
            "password": "123456",
            "is_staff": False,
            "nombre": "Juan",
            "apellido": "Perez",
            "ci": "987654",
            "telefono": "77788888"
        },
        {
            "username": "admin1",
            "email": "admin1@gmail.com",
            "password": "123456",
            "is_staff": True,
            "nombre": "Admin",
            "apellido": "Principal",
            "ci": "7878787",
            "telefono": "77777777"
        },
    ]

    for data in usuarios_data:
        # 1️⃣ Crear Persona
        persona, _ = Persona.objects.get_or_create(
        ci=data.get("ci"),
        defaults={
            "nombre": data["nombre"],
            "apellido": data["apellido"],
            "telefono": data.get("telefono")
        }
    )

        # 2️⃣ Crear User asociado a la persona
        user, created_user = User.objects.get_or_create(
            username=data["username"],
            defaults={
                "email": data.get("email"),
                "persona": persona,
                "is_staff": data.get("is_staff", False),
                "is_active": True,
                "verified": True,
            
            }
        )

        # 3️⃣ Asignar contraseña si se creó el usuario
        if created_user:
            user.set_password(data["password"])
            user.save()

