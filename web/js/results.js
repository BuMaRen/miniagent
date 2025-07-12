function checkResults() {
  const numbers = document.getElementById("drawNumbers").value;
  axios.post(`${apiBase}/results/check`, { numbers })
    .then(res => {
      const ul = document.getElementById("resultList");
      ul.innerHTML = res.data.map(item =>
        `<li>订单ID: ${item.order_id}，用户名: ${item.username}</li>`
      ).join("");
    });
}
