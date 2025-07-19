const apiBase = 'http://localhost:9090';

// 获取方案列表
function loadSchemes() {
  axios.get(`${apiBase}/schemes`)
    .then(res => {
      const select = document.getElementById("schemeSelect");
      select.innerHTML = res.data.map(item =>
        `<option value="${item.id}">${item.name}</option>`
      ).join("");
    });
}

// 创建订单
function createOrder() {
  const username = document.getElementById("username").value;
  const schemeId = document.getElementById("schemeSelect").value;
  const price = document.getElementById("price").value;

  axios.post(`${apiBase}/orders`, { username, scheme_id: schemeId, price })
    .then(() => {
      loadOrders();
      alert("下单成功");
    });
}

// 获取订单列表
function loadOrders() {
  axios.get(`${apiBase}/orders`)
    .then(res => {
      const tbody = document.querySelector("#orderTable tbody");
      tbody.innerHTML = res.data.map(item =>
        `<tr>
    <td>${item.id}</td>
    <td>${item.username}</td>
    <td>${item.scheme_name}</td>
    <td>${item.price}</td>
    <td>${item.create_at}</td>
  </tr>`
      ).join("");
    });
}

window.onload = () => {
  loadSchemes();
  loadOrders();
};
