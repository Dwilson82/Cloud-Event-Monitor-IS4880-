from flask import Flask, render_template, jsonify
import pymysql
import os

app = Flask(__name__)

def get_db_connection():
    return pymysql.connect(
        unix_socket="/cloudsql/project-e3a6924b-8583-4f8a-b9d:us-east1:cloudservereventmonitor",
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASS"],
        database=os.environ["DB_NAME"],
        cursorclass=pymysql.cursors.DictCursor
    )

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/events")
def get_events():
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    message_id AS id,
                    temp_c AS temp,
                    DATE_FORMAT(timestamp_utc, '%H:%i:%s') AS time,
                    is_duplicate AS duplicate,
                    device_id
                FROM messages
                ORDER BY timestamp_utc DESC
                LIMIT 20
            """)
            rows = cursor.fetchall()

        for row in rows:
            row["duplicate"] = bool(row["duplicate"])

        return jsonify(rows)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        if conn:
            conn.close()

@app.route("/api/metrics")
def get_metrics():
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM messages")
            total = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) AS dups FROM messages WHERE is_duplicate = 1")
            dups = cursor.fetchone()["dups"]

            cursor.execute("SELECT AVG(temp_c) AS avg_temp FROM messages")
            avg_temp = cursor.fetchone()["avg_temp"]

        return jsonify({
            "total": total,
            "dups": dups,
            "avg_temp": round(avg_temp, 1) if avg_temp is not None else 0
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        if conn:
            conn.close()

@app.route("/api/chart-data")
def chart_data():
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    DATE_FORMAT(timestamp_utc, '%H:%i:%s') AS label,
                    temp_c AS temp
                FROM messages
                ORDER BY timestamp_utc DESC
                LIMIT 20
            """)
            rows = cursor.fetchall()

        rows.reverse()

        return jsonify({
            "labels": [r["label"] for r in rows],
            "temps": [float(r["temp"]) for r in rows]
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        if conn:
            conn.close()