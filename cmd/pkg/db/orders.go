package db

import "database/sql"

func CreateOrdersTable(db *sql.DB) error {
	sqlStr := `CREATE TABLE IF NOT EXISTS orders (
  id INT PRIMARY KEY AUTO_INCREMENT,
  username VARCHAR(255),
  scheme_id INT,
  price INT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)`
	_, err := db.Exec(sqlStr)
	return err
}
