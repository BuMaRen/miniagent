package db

import (
	"database/sql"
	"fmt"
	"lottery/pkg/schemas"
	"strings"
)

func QueryResults(db *sql.DB, number int) ([]*schemas.Winner, error) {
	sqlStr := fmt.Sprintf("SELECT name FROM schemes WHERE numbers LIKE '%% %d %%' OR numbers LIKE '%d %%' OR numbers LIKE '%% %d' OR numbers = '%d'", number, number, number, number)
	rows, err := db.Query(sqlStr)
	if err != nil {
		return nil, err
	}
	// 获取所有的中奖方案
	schemasList := []any{}
	for rows.Next() {
		var scheme string
		if err := rows.Scan(&scheme); err != nil {
			return nil, err
		}
		schemasList = append(schemasList, scheme)
	}
	rows.Close()

	placeholders := strings.Repeat("?,", len(schemasList))
	placeholders = strings.TrimRight(placeholders, ",")
	sqlStr = fmt.Sprintf("SELECT id, username, scheme_name, price, created_at FROM orders WHERE scheme_name IN (%s)", placeholders)
	rows, err = db.Query(sqlStr, schemasList...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var orders []*schemas.Winner
	for rows.Next() {
		order := &schemas.Winner{}
		if err := rows.Scan(&order.OrderId, &order.UserName, &order.SchemeName, &order.Price, &order.CreateAt); err != nil {
			return nil, err
		}
		orders = append(orders, order)
	}
	return orders, nil
}
