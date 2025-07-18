package db

import (
	"database/sql"
	"lottery/pkg/schemas"
)

func CreateOrdersTable(db *sql.DB) error {
	sqlStr := `CREATE TABLE IF NOT EXISTS orders (
  id INT PRIMARY KEY AUTO_INCREMENT,
  username VARCHAR(255),
  scheme_name VARCHAR(255),
  price INT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)`
	_, err := db.Exec(sqlStr)
	return err
}

func GetAllOrders(db *sql.DB) ([]schemas.Order, error) {
	rows, err := db.Query("SELECT id, username, scheme_name, price, created_at FROM orders")
	if err != nil {
		return nil, err // Handle error appropriately in production code
	}
	defer rows.Close()

	var orders []schemas.Order
	for rows.Next() {
		var order schemas.Order
		if err := rows.Scan(&order.Id, &order.UserName, &order.SchemeName, &order.Price, &order.CreateAt); err != nil {
			return nil, err // Handle error appropriately in production code
		}
		orders = append(orders, order)
	}
	if err := rows.Err(); err != nil {
		return nil, err // Handle error appropriately in production code
	}
	return orders, nil
}

func CreateOrder(db *sql.DB, order *schemas.NewOrder) error {
	sqlStr := `INSERT INTO orders (username, scheme_name, price) VALUES (?, ?, ?)`
	_, err := db.Exec(sqlStr, order.UserName, order.SchemeName, order.Price)
	if err != nil {
		return err // Handle error appropriately in production code
	}
	return nil
}
