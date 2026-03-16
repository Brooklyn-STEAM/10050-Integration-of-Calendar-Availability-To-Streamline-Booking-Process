import smtplib

email = "bookwellfsd@gmail.com"
password = "ispiwtsqqgbqahnj"

server = smtplib.SMTP("smtp.gmail.com", 587)
server.starttls()

server.login(email, password)

print("LOGIN SUCCESS")