package schemas

type DrawNumbers struct {
	Numbers string `json:"numbers"`
}

type Winner struct {
	OrderId  int    `json:"order_id"`
	UserName string `json:"username"`
	Price    int    `json:"price"`
}
