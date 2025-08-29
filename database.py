import sqlite3

def create_database():
    # This will create a database file named 'whatsapp_reminder.db'
    conn = sqlite3.connect('whatsapp_reminder.db')
    cursor = conn.cursor()

    # Create the users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        whatsapp_id TEXT NOT NULL UNIQUE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    ''')

    # Create the reminders table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        reminder_time DATETIME NOT NULL,
        is_sent INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    );
    ''')

    print("Database and tables created successfully!")

    # Commit the changes and close the connection
    conn.commit()
    conn.close()

if _name_ == '_main_':
    create_database()
