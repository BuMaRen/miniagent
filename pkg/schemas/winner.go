package schemas

type DrawNumbers struct {
	Numbers string `json:"numbers"`
}

type Winner struct {
	OrderId    int    `json:"order_id"`
	UserName   string `json:"username"`
	SchemeName string `json:"scheme_name"`
	Price      int    `json:"price"`
	CreateAt   string `json:"created_at"`
}
