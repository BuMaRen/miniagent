package schemas

type Scheme struct {
	Id      int    `json:"id"`
	Name    string `json:"name"`
	Numbers string `json:"numbers"`
}

type NewScheme struct {
	Name    string `json:"name"`
	Numbers string `json:"numbers"`
}
