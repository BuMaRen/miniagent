package orders

import "github.com/gin-gonic/gin"

func RegisterHandlers(router *gin.Engine) {
	router.GET("/orders", GetAllOrders)
	router.POST("/orders", CreateOrders)
}
