package schemas

type Order struct {
	Id         int    `json:"id"`
	UserName   string `json:"username"`
	SchemeName string `json:"scheme_name"`
	Price      int    `json:"price"`
	CreateAt   string `json:"create_at"`
}

type NewOrder struct {
	UserName   string `json:"username"`
	SchemeName string `json:"scheme_name"`
	Price      int    `json:"price"`
}
