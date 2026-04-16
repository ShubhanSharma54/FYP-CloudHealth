import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "cloudhealth.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
    except:
        pass  # WAL might already be enabled
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            instance_id TEXT,
            region TEXT,
            status TEXT DEFAULT 'running',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL,
            cpu_usage REAL,
            memory_usage REAL,
            disk_usage REAL,
            network_in REAL,
            network_out REAL,
            disk_io REAL,
            uptime_seconds INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (server_id) REFERENCES servers (id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS detailed_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL,
            instance_id TEXT,
            hostname TEXT,
            source TEXT,
            cpu_percent REAL,
            cpu_cores_physical INTEGER,
            cpu_cores_logical INTEGER,
            memory_percent REAL,
            memory_used_mb REAL,
            memory_available_mb REAL,
            memory_total_mb REAL,
            swap_percent REAL,
            swap_used_mb REAL,
            swap_total_mb REAL,
            disk_percent REAL,
            disk_used_gb REAL,
            disk_free_gb REAL,
            disk_total_gb REAL,
            disk_read_mb REAL,
            disk_write_mb REAL,
            disk_read_ops INTEGER,
            disk_write_ops INTEGER,
            network_in_mb_s REAL,
            network_out_mb_s REAL,
            network_packets_in INTEGER,
            network_packets_out INTEGER,
            network_errors_in INTEGER,
            network_errors_out INTEGER,
            processes_count INTEGER,
            uptime_seconds INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (server_id) REFERENCES servers (id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (server_id) REFERENCES servers (id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            status TEXT DEFAULT 'success',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (server_id) REFERENCES servers (id)
        )
    """)
    
    cursor.execute("SELECT COUNT(*) FROM servers")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO servers (name, instance_id, region, status)
            VALUES ('CloudHealth-Monitor-Server', 'i-0123456789abcdef0', 'us-east-1', 'running')
        """)
        
        server_id = cursor.lastrowid
        
        import random
        for i in range(24):
            hours_ago = 23 - i
            cpu = random.randint(40, 85)
            memory = random.randint(50, 80)
            disk = random.randint(40, 60)
            
            cursor.execute("""
                INSERT INTO metrics (server_id, cpu_usage, memory_usage, disk_usage, 
                                    network_in, network_out, disk_io, uptime_seconds, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '-' || ? || ' hours'))
            """, (server_id, cpu, memory, disk, 
                  random.randint(100000, 500000), random.randint(50000, 200000),
                  random.randint(1000, 5000), random.randint(280000, 300000), hours_ago))
        
        alerts_data = [
            ('high_cpu', 'warning', 'High CPU usage detected: 85%', 2),
            ('low_disk', 'critical', 'Disk space running low: 15% remaining', 5),
            ('server_down', 'critical', 'Server unreachable', 12),
            ('high_memory', 'warning', 'Memory usage above 80%', 8),
            ('high_cpu', 'info', 'CPU usage normalized', 1),
        ]
        
        for alert_type, severity, message, hours in alerts_data:
            cursor.execute("""
                INSERT INTO alerts (server_id, alert_type, severity, message, timestamp)
                VALUES (?, ?, ?, ?, datetime('now', '-' || ? || ' hours'))
            """, (server_id, alert_type, severity, message, hours))
        
        logs_data = [
            ('Log downloaded', 'success', 1),
            ('CPU alert triggered', 'warning', 2),
            ('Report generated', 'success', 3),
            ('Server health check', 'success', 4),
            ('Memory threshold exceeded', 'warning', 6),
            ('Disk cleanup completed', 'success', 8),
        ]
        
        for action, status, hours in logs_data:
            cursor.execute("""
                INSERT INTO logs (server_id, action, status, timestamp)
                VALUES (?, ?, ?, datetime('now', '-' || ? || ' hours'))
            """, (server_id, action, status, hours))
    
    conn.commit()
    conn.close()
    print("Database initialized successfully!")

if __name__ == "__main__":
    init_db()
